"""Paper-only bridge worker for fresh Tier-1 early explosive events.

The observational service discovers events; this worker consumes fresh events and
runs the existing surge gate -> risk gate -> paper trade -> monitor -> outcome
lifecycle. It never enables or submits live broker orders.
"""
from __future__ import annotations

import os
import signal
import time
from datetime import datetime

from src.dashboard_control import entries_allowed, append_audit
from src.capital_manager import get_available_capital
from src.market_scanner import get_client
from src.production_guard import write_heartbeat
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.tier1_option_observer import get_tier1_option_observer
from src.surge_trade_bridge import create_surge_trade
from src.live_trade_monitor import run_monitor
from src.trading_risk_manager import TradingRiskManager
from src.rejection_recorder import record_rejection
from src.upgrade_config import MAX_TRADES_PER_DAY, ENTRY_START, LAST_ENTRY
from src.session_clock import IST, is_weekday

RUNNING = True
POLL_SECONDS = max(1, int(os.getenv("SURGE_TRADE_BRIDGE_INTERVAL_SECONDS", "2")))
RISK_MANAGER = TradingRiskManager()


def _stop(*_args):
    global RUNNING
    RUNNING = False


def _in_entry_session() -> bool:
    now = datetime.now(IST)
    return is_weekday(now) and ENTRY_START <= now.time() <= LAST_ENTRY


def _process_once() -> bool:
    if not entries_allowed() or not _in_entry_session():
        return False

    try:
        client = get_client()
        capital = get_available_capital(client, paper_mode=True)
        allowed, _reason, _summary = can_open_new_trade(MAX_TRADES_PER_DAY, None, capital)
        if not allowed:
            return False
    except Exception as exc:
        write_heartbeat("surge_bridge_capital_error", error=str(exc))
        return False

    observer = get_tier1_option_observer()
    events = observer.get_pending_early_events(limit=5)
    if not events:
        return False

    # Strongest fresh event first; the existing gates remain authoritative.
    events.sort(key=lambda e: float(e.get("score", 0) or 0), reverse=True)
    for event in events:
        event_id = int(event["id"])
        symbol = str(event.get("symbol") or "")
        option_type = str(event.get("option_type") or "").upper()
        try:
            trade, result = create_surge_trade(event, capital, RISK_MANAGER)
        except Exception as exc:
            print(f"[SURGE BRIDGE] evaluation failed for {symbol} {option_type}: {exc}")
            continue

        if trade is None:
            reason_text = str(result.get("reason") or "SURGE_REJECTED")
            if reason_text != "EVENT_ALREADY_CLAIMED":
                print(f"[SURGE BRIDGE] {symbol} {option_type} rejected: {reason_text}")
                try:
                    record_rejection(
                        symbol=symbol,
                        score=event.get("score"),
                        reason=f"SURGE:{reason_text}",
                        features={"event": event, "result": result},
                    )
                except Exception as exc:
                    print(f"[SURGE BRIDGE] rejection persistence failed: {exc}")
            if result.get("terminal"):
                observer.mark_early_event_consumed(event_id)
            continue

        trade["strategy"] = "SURGE_EARLY_EXPLOSIVE"
        trade["surge_score"] = result.get("gate", {}).get("score", 0)
        trade["surge_reasons"] = result.get("gate", {}).get("reasons", [])
        append_audit(
            "SURGE_PAPER_TRADE_CREATED",
            f"{symbol} {option_type} score={trade['surge_score']}",
            str(event.get("event_key") or ""),
            "RECORDED",
        )
        write_heartbeat(
            "surge_paper_trade",
            symbol=symbol,
            contract=trade.get("contract"),
            strategy=trade["strategy"],
        )
        print(
            f"[SURGE BRIDGE] PAPER TRADE {trade.get('contract')} "
            f"score={trade['surge_score']} qty={trade.get('quantity')}"
        )
        try:
            send_entry_alert(trade)
        except Exception as exc:
            print(f"[SURGE BRIDGE] Telegram entry alert failed: {exc}")

        try:
            result_monitor = run_monitor(trade)
        except Exception as exc:
            write_heartbeat("surge_monitor_error", symbol=symbol, error=str(exc))
            print(f"[SURGE BRIDGE] monitor failed; event remains unconsumed: {exc}")
            return True

        if result_monitor is None:
            return True

        observer.mark_early_event_consumed(event_id)
        try:
            append_audit(
                "SURGE_PAPER_TRADE_CLOSED",
                f"{symbol} {option_type} pnl={result_monitor.get('pnl', 0)} reason={result_monitor.get('exit_reason', '')}",
                str(event.get("event_key") or ""),
                "RECORDED",
            )
        except Exception:
            pass
        return True

    return False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("PEREZ AI Surge Trade Bridge — PAPER ONLY")
    while RUNNING:
        try:
            did_work = _process_once()
        except Exception as exc:
            print(f"[SURGE BRIDGE] cycle failed safely: {exc}")
            did_work = False
        time.sleep(1 if did_work else POLL_SECONDS)


if __name__ == "__main__":
    main()
