#!/usr/bin/env python3
"""Safely patch PEREZ paper-position crash recovery; run from repo root."""
from pathlib import Path
from datetime import datetime
import json, os, shutil, subprocess, sys

R = Path.cwd()
if not (R / "src/trade_engine.py").is_file():
    raise SystemExit("Run from ~/PEREZ-AI-Trading-Bot")
names = [
    "src/surge_trade_bridge.py", "src/live_trade_monitor.py",
    "src/trade_monitor.py", "src/paper_position_recovery.py",
    "src/paper_trade_lifecycle.py", "src/trade_engine.py",
]
paths = {n: R / n for n in names}
test_path = R / "tests/test_paper_crash_recovery.py"
if test_path.exists():
    raise SystemExit("Refusing to overwrite tests/test_paper_crash_recovery.py")

def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {n}")
    return s.replace(old, new, 1)

def bridge(s):
    a = '    record_event(trade, "DETECTED", ts=trade["detected_at"] or None,\n'
    b = '''    # Promote only after risk registration is durable. Keep PENDING on failure.
    try:
        from src.active_position_guard import mark_claim_active
        mark_claim_active(trade["contract"], trade_id, trade)
    except Exception as exc:
        result["eligible"] = False
        result["terminal"] = False
        result["reason"] = f"CLAIM_ACTIVATION_FAILED:{type(exc).__name__}"
        result["reasons"] = [result["reason"]]
        return None, result

'''
    return once(s, a, b + a, "bridge activation")

def live(s):
    for line in (
        '                    release_contract(trade["contract"], trade.get("trade_id"))\n',
        '                release_contract(trade["contract"], trade.get("trade_id"))\n',
    ):
        s = once(s, line, "", "premature monitor release")
    a = '                return {**result, "record": record}\n'
    b = '                # Release only after durable CLOSE and final accounting.\n                release_contract(trade["contract"], trade.get("trade_id"))\n'
    return once(s, a, b + a, "final monitor release")

def trade_monitor(s):
    a = '''    if result["closed"]:
        release_contract(trade["contract"], trade.get("trade_id"))
    return result
'''
    return once(s, a, "    return result\n", "trade_monitor release")

reconstruct = r'''def _reconstruct(row, events):
    """Rebuild only ACTIVE claims; payload closes the claim-before-OPEN crash gap."""
    tid = str(row[2])
    status = str(row[4] if len(row) > 4 and row[4] is not None else "ACTIVE").upper()
    if status != "ACTIVE":
        return None
    evs = events.get(tid, [])
    if any(e.get("event") == "CLOSE" for e in evs):
        return None
    opened = next((e for e in evs if e.get("event") == "OPEN"), None)
    contract, symbol = str(row[0]), str(row[1])
    payload = {}
    if len(row) > 5 and row[5]:
        try:
            value = json.loads(row[5])
            if isinstance(value, dict):
                payload = value
        except (TypeError, ValueError):
            return None
    if not payload and not opened:
        return None
    opened = opened or {}
    detected = next((e for e in evs if e.get("event") == "DETECTED"), None)
    detected_id = detected.get("event_id") if detected else None
    if detected_id and not payload.get("token") and not opened.get("token"):
        try:
            db = sqlite3.connect("data/memory/tier1_option_moves.sqlite3")
            token_row = db.execute("SELECT instrument_key FROM early_events WHERE id=?",
                                   (int(detected_id),)).fetchone()
            db.close()
            if token_row and token_row[0]:
                payload["token"] = str(token_row[0])
        except Exception as exc:
            print(f"[RECOVERY] detection token lookup failed: {exc}")

    def pick(key, *fallbacks):
        value = payload.get(key)
        if value not in (None, ""):
            return value
        return next((v for v in fallbacks if v not in (None, "")), None)

    qty = int(pick("quantity", opened.get("quantity")) or 0)
    original = int(pick("original_quantity", opened.get("original_quantity"), qty) or qty)
    partial = next((e for e in reversed(evs) if e.get("event") == "TARGET1_PARTIAL"), None)
    remaining = partial.get("remaining_quantity") if partial else None
    if remaining in (None, ""):
        remaining = pick("remaining_quantity", qty)
    realized = (partial.get("realized_pnl") if partial and partial.get("realized_pnl") is not None
                else pick("realized_pnl", 0))
    trade = dict(payload)
    trade.update({
        "trade_id": tid, "lineage_id": str(pick("lineage_id", opened.get("lineage_id"), tid) or tid),
        "symbol": symbol, "contract": contract,
        "signal": str(pick("signal", opened.get("signal"), "BUY CE")),
        "exchange": str(pick("exchange", opened.get("exchange"), "NFO")),
        "token": str(pick("token", opened.get("token"), _token_for(contract)) or ""),
        "entry": float(pick("entry", opened.get("entry")) or 0),
        "quantity": qty, "original_quantity": original, "remaining_quantity": int(remaining or 0),
        "initial_stop_loss": float(pick("initial_stop_loss", opened.get("initial_stop_loss"),
                                        opened.get("stop_loss")) or 0),
        "stop_loss": float(pick("stop_loss", opened.get("stop_loss")) or 0),
        "target1": float(pick("target1", opened.get("target1")) or 0),
        "target2": float(pick("target2", opened.get("target2"), opened.get("target")) or 0),
        "target": float(pick("target2", opened.get("target2"), opened.get("target")) or 0),
        "partial_booked": bool(payload.get("partial_booked") or partial),
        "realized_pnl": float(realized or 0), "status": "PAPER TRADE ACTIVE",
        "live_orders": False, "strategy": str(pick("strategy", opened.get("strategy"), "CORE")),
        "detected_at": str(pick("detected_at", opened.get("detected_at"),
                                detected.get("ts_utc") if detected else "") or ""),
        "opened_at": str(pick("opened_at", opened.get("ts_utc"), opened.get("opened_at")) or ""),
    })
    if not all((trade["entry"], trade["quantity"], trade["remaining_quantity"],
                trade["stop_loss"], trade["target1"], trade["target2"])):
        return None
    return trade

'''

def recovery(s):
    a, b = s.find("def _reconstruct(row, events):"), s.find("def _monitor(trade):")
    if a < 0 or b < 0:
        raise RuntimeError("recovery function boundaries not found")
    s = s[:a] + reconstruct + s[b:]
    s = once(s, "from src.active_position_guard import active_contracts\n",
             "from src.active_position_guard import active_contracts, release_contract\n",
             "recovery imports")
    old = '''    for row in rows:
        trade = _reconstruct(row, events)
        if not trade:
            print(f"[RECOVERY] skipped already-closed/unrecoverable trade {row[2]}")
            continue
'''
    new = '''    for row in rows:
        trade_id = str(row[2])
        state = str(row[4] if len(row) > 4 and row[4] is not None else "ACTIVE").upper()
        if state != "ACTIVE":
            print(f"[RECOVERY] PENDING claim retained for manual reconciliation: {trade_id}")
            continue
        row_events = events.get(trade_id, [])
        close_event = next((e for e in reversed(row_events) if e.get("event") == "CLOSE"), None)
        if close_event:
            # CLOSE is written before risk accounting. Replay by result_id so a
            # crash in that window cannot lose the daily/lineage result.
            try:
                from src.trading_risk_manager import TradingRiskManager
                risk_manager = TradingRiskManager()
                risk_manager.record_trade_result(
                    str(close_event.get("lineage_id") or trade_id),
                    float(close_event.get("pnl") or 0.0),
                    stop_loss=str(close_event.get("exit_reason") or "").upper()
                               in {"STOP_LOSS", "TRAILING_STOP"},
                    result_id=trade_id,
                )
            except Exception as exc:
                print(f"[RECOVERY] CLOSE risk reconciliation failed; claim retained: {trade_id}: {exc}")
                continue
            release_contract(row[0], trade_id)
            print(f"[RECOVERY] reconciled CLOSE and released claim for {trade_id}")
            continue
        trade = _reconstruct(row, events)
        if not trade:
            print(f"[RECOVERY] ACTIVE claim retained; trade is incomplete: {trade_id}")
            continue
'''
    return once(s, old, new, "recovery loop")

def lifecycle(s):
    a = s.find("    # Recovery and the original monitor can race to finalize one trade.")
    if a < 0:
        raise RuntimeError("CLOSE idempotency block not found")
    marker = '        return instant.isoformat(timespec="milliseconds")\n'
    p = s.find(marker, a)
    if p < 0:
        raise RuntimeError("CLOSE return anchor not found")
    e = p + len(marker)
    block = '''    # Cross-thread/process idempotency. Read failures abort the CLOSE write.
    if payload["event"] == "CLOSE" and payload["trade_id"]:
        with _CLOSE_EVENT_LOCK:
            LIFECYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with LIFECYCLE_LOG.open("a+", encoding="utf-8") as existing:
                fcntl.flock(existing.fileno(), fcntl.LOCK_EX)
                try:
                    existing.seek(0)
                    for line in existing:
                        try:
                            prior = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if prior.get("event") == "CLOSE" and str(prior.get("trade_id") or "") == payload["trade_id"]:
                            return str(prior.get("ts_utc") or instant.isoformat(timespec="milliseconds"))
                    existing.seek(0, os.SEEK_END)
                    existing.write(json.dumps(payload, separators=(",", ":"), default=str) + "\\n")
                    existing.flush()
                    os.fsync(existing.fileno())
                finally:
                    fcntl.flock(existing.fileno(), fcntl.LOCK_UN)
        return instant.isoformat(timespec="milliseconds")
'''
    s = s[:a] + block + s[e:]
    if "import fcntl\n" not in s:
        s = s.replace("import json\n", "import json\nimport fcntl\nimport os\n", 1)
    return s

test_source = r'''import json
import threading
from pathlib import Path
from src import paper_position_recovery as recovery
from src import paper_trade_lifecycle as lifecycle

def payload():
    return {"trade_id":"recover-001","lineage_id":"lineage-001","symbol":"NIFTY",
            "contract":"NIFTY26NOV25000CE","signal":"BUY CE","exchange":"NFO",
            "token":"NSE_FO|test-token","entry":100.0,"quantity":25,
            "original_quantity":25,"remaining_quantity":25,"initial_stop_loss":90.0,
            "stop_loss":90.0,"target1":115.0,"target2":130.0,"target":130.0,
            "partial_booked":False,"realized_pnl":0.0,"opened_at":"2026-11-02T10:00:00+00:00",
            "status":"PAPER TRADE ACTIVE","live_orders":False,"strategy":"SURGE_EARLY_EXPLOSIVE"}

def row(p, status="ACTIVE"):
    return (p["contract"], p["symbol"], p["trade_id"], "2026-11-02T10:00:00+00:00",
            status, json.dumps(p))

def test_pending_claim_is_not_reconstructed():
    p = payload()
    assert recovery._reconstruct(row(p, "PENDING"), {}) is None

def test_active_claim_recovers_without_open_event():
    p = payload()
    trade = recovery._reconstruct(row(p), {})
    assert trade["trade_id"] == p["trade_id"] and trade["token"] == p["token"]
    assert trade["remaining_quantity"] == 25 and trade["live_orders"] is False

def test_recovery_uses_latest_partial_state():
    p = payload()
    events = {p["trade_id"]:[{"event":"TARGET1_PARTIAL","remaining_quantity":12,"realized_pnl":37.5}]}
    trade = recovery._reconstruct(row(p), events)
    assert trade["partial_booked"] and trade["remaining_quantity"] == 12
    assert trade["realized_pnl"] == 37.5

def test_close_event_prevents_reconstruction():
    p = payload()
    events = {p["trade_id"]:[{"event":"CLOSE","trade_id":p["trade_id"]}]}
    assert recovery._reconstruct(row(p), events) is None

def test_close_is_idempotent(tmp_path, monkeypatch):
    log = tmp_path / "events.jsonl"
    monkeypatch.setattr(lifecycle, "LIFECYCLE_LOG", log)
    monkeypatch.setattr(lifecycle, "_CLOSE_EVENT_LOCK", threading.Lock())
    trade = {"trade_id":"close-001","symbol":"NIFTY","contract":"NIFTY26NOV25000CE"}
    first = lifecycle.record_event(trade, "CLOSE", pnl=10)
    second = lifecycle.record_event(trade, "CLOSE", pnl=10)
    assert first == second and len(log.read_text().splitlines()) == 1

def test_closed_claim_replays_risk_result_before_release(monkeypatch):
    p = payload()
    close = {"event":"CLOSE","trade_id":p["trade_id"],"lineage_id":p["lineage_id"],
             "pnl":-22.5,"exit_reason":"STOP_LOSS"}
    released = []
    calls = []
    class FakeRiskManager:
        def record_trade_result(self, identity, pnl, *, stop_loss, result_id):
            calls.append((identity, pnl, stop_loss, result_id))
            return True
    from src import trading_risk_manager
    monkeypatch.setattr(trading_risk_manager, "TradingRiskManager", FakeRiskManager)
    monkeypatch.setattr(recovery, "active_contracts", lambda: [row(p)])
    monkeypatch.setattr(recovery, "_events", lambda: {p["trade_id"]:[close]})
    monkeypatch.setattr(recovery, "release_contract",
                        lambda contract, trade_id: released.append((contract, trade_id)))
    assert recovery.recover_paper_positions() == 0
    assert calls == [(p["lineage_id"], -22.5, True, p["trade_id"])]
    assert released == [(p["contract"], p["trade_id"])]
'''

def main():
    for n, p in paths.items():
        if not p.is_file():
            raise SystemExit(f"Missing required file: {n}")
    originals = {n: p.read_text(encoding="utf-8") for n, p in paths.items()}
    engine_source = originals["src/trade_engine.py"]
    if "trade_payload=trade" in engine_source:
        engine_source = engine_source.replace("trade_payload=trade", "trade", 1)
    elif "trade_payload = trade" in engine_source:
        engine_source = engine_source.replace("trade_payload = trade", "trade", 1)
    elif "trade_payload" in engine_source:
        raise RuntimeError("unexpected trade_payload call format; refusing unsafe edit")
    updated = {
        names[0]: bridge(originals[names[0]]),
        names[1]: live(originals[names[1]]),
        names[2]: trade_monitor(originals[names[2]]),
        names[3]: recovery(originals[names[3]]),
        names[4]: lifecycle(originals[names[4]]),
        "src/trade_engine.py": engine_source,
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups, changed = {}, []
    try:
        for n, p in paths.items():
            b = p.with_name(p.name + ".pre_crash_fix_" + stamp)
            shutil.copy2(p, b)
            backups[n] = b
        for n, content in updated.items():
            tmp = paths[n].with_suffix(paths[n].suffix + ".crashfix.tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(paths[n]); changed.append(n)
        test_path.write_text(test_source, encoding="utf-8"); changed.append("TEST")
        py = R / "venv/bin/python"
        if not py.is_file():
            raise RuntimeError("venv/bin/python not found")
        c = subprocess.run([str(py), "-m", "compileall", "-q", *names], cwd=R, text=True, capture_output=True)
        if c.returncode:
            raise RuntimeError("compileall failed:\n" + c.stdout + c.stderr)
        d = subprocess.run(["git", "diff", "--check"], cwd=R, text=True, capture_output=True)
        if d.returncode:
            raise RuntimeError("git diff --check failed:\n" + d.stdout + d.stderr)
        suite = ["tests/test_paper_crash_recovery.py", "tests/test_paper_exit.py",
                 "tests/test_paper_trade_lifecycle.py", "tests/test_trade_engine_routing.py",
                 "tests/test_surge_trade_gate.py", "tests/test_trading_risk_manager.py"]
        t = subprocess.run([str(py), "-m", "pytest", "-q", *suite], cwd=R, text=True, capture_output=True)
        print(t.stdout)
        if t.stderr: print(t.stderr, file=sys.stderr)
        if t.returncode: raise RuntimeError(f"pytest failed ({t.returncode})")
        print("PATCH APPLIED; compileall, diff check and regression tests passed.")
        for n, b in backups.items(): print("BACKUP:", b.name)
        print("No services restarted; no strategy, risk, or environment settings changed.")
        return 0
    except Exception as exc:
        print("PATCH FAILED:", exc, file=sys.stderr)
        for n in reversed(changed):
            if n == "TEST":
                if test_path.exists(): test_path.unlink()
            elif n in backups:
                shutil.copy2(backups[n], paths[n])
        print("Rollback completed; backups retained.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
