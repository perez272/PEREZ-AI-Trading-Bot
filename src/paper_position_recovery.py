import json
import os
import threading
from pathlib import Path

from src.active_position_guard import active_contracts, release_contract
from src.live_trade_monitor import run_monitor
import sqlite3
from src.alternative_market_data import get_upstox_client

LIFECYCLE = Path("data/paper_trade_lifecycle.jsonl")
INSTRUMENTS = Path("data/instruments.json")
_threads = {}

def _events():
    if not LIFECYCLE.exists():
        return {}
    latest = {}
    with LIFECYCLE.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            tid = str(e.get("trade_id") or "")
            if tid:
                latest.setdefault(tid, []).append(e)
    return latest

def _token_for(contract):
    if not INSTRUMENTS.exists():
        return ""
    try:
        data = json.loads(INSTRUMENTS.read_text())
    except Exception:
        return ""

    def walk(x):
        if isinstance(x, dict):
            text = " ".join(str(x.get(k, "")) for k in
                            ("contract","name","trading_symbol","tradingsymbol","symbol"))
            if contract.upper() in text.upper():
                return str(x.get("token") or x.get("instrument_token") or
                           x.get("exchange_token") or "")
            for v in x.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(x, list):
            for v in x:
                r = walk(v)
                if r:
                    return r
        return ""
    return walk(data)

def _reconstruct(row, events):
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

def _monitor(trade):
    try:
        print(f"[RECOVERY] monitoring {trade['contract']} | trade_id={trade['trade_id']}")
        run_monitor(trade)
        print(f"[RECOVERY] monitor finished {trade['contract']}")
    except Exception as exc:
        print(f"[RECOVERY] monitor failed {trade['contract']}: {exc}")
    finally:
        _threads.pop(trade["trade_id"], None)

def recover_paper_positions():
    if os.getenv("PAPER_MODE", "true").strip().lower() != "true":
        print("[RECOVERY] skipped — PAPER_MODE is not true")
        return 0

    rows = active_contracts()
    if not rows:
        print("[RECOVERY] no persisted active paper positions")
        return 0

    events = _events()
    started = 0

    for row in rows:
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
        if not trade["token"]:
            try:
                client = get_upstox_client()
                chain = client.get_option_chain(trade["symbol"])
                wanted = trade["contract"].upper().strip()
                for row in chain or []:
                    if not isinstance(row, dict):
                        continue
                    for side in ("call_options", "put_options"):
                        option = row.get(side) or {}
                        if not isinstance(option, dict):
                            continue
                        trading_symbol = str(option.get("trading_symbol") or "").upper().strip()
                        if trading_symbol == wanted:
                            key = str(option.get("instrument_key") or "").strip()
                            if key:
                                trade["token"] = key
                                resolved = client.resolve_option_by_instrument_key(
                                    trade["symbol"], key
                                )
                                if resolved:
                                    trade["exchange"] = resolved.get("exchange") or trade["exchange"]
                                    trade["expiry"] = resolved.get("expiry") or trade["expiry"]
                                    trade["strike"] = resolved.get("strike") or trade["strike"]
                                    trade["signal"] = "BUY " + str(resolved.get("option_type") or "CE")
                                print(f"[RECOVERY] resolved live contract {wanted} -> {key}")
                            break
                    if trade["token"]:
                        break
            except Exception as exc:
                print(f"[RECOVERY] live contract lookup failed: {exc}")
        if not trade["token"]:
            print(f"[RECOVERY] skipped — no live instrument token: {trade['contract']}")
            continue
        if trade["trade_id"] in _threads:
            continue

        t = threading.Thread(target=_monitor, args=(trade,),
                             name=f"paper-recovery-{trade['trade_id'][:8]}",
                             daemon=True)
        _threads[trade["trade_id"]] = t
        t.start()
        started += 1

    print(f"[RECOVERY] reattached {started} persisted paper monitor(s)")
    return started
