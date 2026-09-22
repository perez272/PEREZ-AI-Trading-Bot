import json
import os
import threading
from pathlib import Path

from src.active_position_guard import active_contracts
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
    tid = str(row[2])
    evs = events.get(tid, [])
    opened = next((e for e in evs if e.get("event") == "OPEN"), None)
    if not opened or any(e.get("event") == "CLOSE" for e in evs):
        return None

    contract = str(row[0])
    symbol = str(row[1])
    if not opened:
        return None

    detected = next((e for e in evs if e.get("event") == "DETECTED"), None)
    detected_id = detected.get("event_id") if detected else None
    if detected_id:
        try:
            db = sqlite3.connect("data/memory/tier1_option_moves.sqlite3")
            row = db.execute(
                "SELECT instrument_key FROM early_events WHERE id=?",
                (int(detected_id),),
            ).fetchone()
            db.close()
            if row and row[0]:
                opened["token"] = str(row[0])
        except Exception as exc:
            print(f"[RECOVERY] detection token lookup failed: {exc}")

    return {
        "trade_id": tid,
        "lineage_id": str(opened.get("lineage_id") or tid),
        "symbol": symbol,
        "signal": str(opened.get("signal") or "BUY CE"),
        "contract": contract,
        "exchange": str(opened.get("exchange") or "NFO"),
        "token": str(opened.get("token") or _token_for(contract)),
        "entry": float(opened.get("entry") or 0),
        "quantity": int(opened.get("quantity") or 0),
        "original_quantity": int(opened.get("original_quantity") or opened.get("quantity") or 0),
        "remaining_quantity": int(opened.get("remaining_quantity") or opened.get("quantity") or 0),
        "initial_stop_loss": float(opened.get("initial_stop_loss") or opened.get("stop_loss") or 0),
        "stop_loss": float(opened.get("stop_loss") or 0),
        "target1": float(opened.get("target1") or 0),
        "target2": float(opened.get("target2") or opened.get("target") or 0),
        "target": float(opened.get("target2") or opened.get("target") or 0),
        "partial_booked": bool(opened.get("partial_booked", False)),
        "realized_pnl": float(opened.get("realized_pnl") or 0),
        "status": "PAPER TRADE ACTIVE",
        "live_orders": False,
        "strategy": str(opened.get("strategy") or "CORE"),
        "detected_at": str(opened.get("detected_at") or ""),
        "opened_at": str(opened.get("ts_utc") or opened.get("opened_at") or ""),
    }

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
        trade = _reconstruct(row, events)
        if not trade:
            print(f"[RECOVERY] skipped already-closed/unrecoverable trade {row[2]}")
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
