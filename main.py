import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate
from src.production_guard import acquire_single_instance, release_single_instance, write_heartbeat
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade, resolve_option_contract
from src.options_engine_adapter import evaluate_option_candidate
from src.high_conviction_discovery import discover
from src.upgrade_config import (
    RESCAN_DELAY_SECONDS,
    MINIMUM_SCORE,
    MAX_TRADES_PER_DAY,
    MAX_DAILY_LOSS,
    OPTIONS_MIN_SCORE,
)

CAPITAL = 50000
IST = ZoneInfo("Asia/Kolkata")


def wait_for_0915_ist():
    start = dt_time(9, 15)
    while True:
        now = datetime.now(IST)
        if now.time() >= start:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR 09:15 IST — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def main():
    lock = acquire_single_instance()
    write_heartbeat("starting")
    try:
        wait_for_0915_ist()
        print("=" * 72)
        print("PEREZ AI PAPER-TRADING BOT — PRODUCTION HARDENED")
        print("Paper mode only — no real orders are placed.")
        print("09:15 IST — fresh-data scanning enabled.")
        print(f"Market score threshold: {MINIMUM_SCORE} | Options threshold: {OPTIONS_MIN_SCORE}")
        print(f"Rescan interval: {RESCAN_DELAY_SECONDS}s")
        print("=" * 72)

        while True:
            write_heartbeat("scanning")
            allowed, reason, summary = can_open_new_trade(MAX_TRADES_PER_DAY, MAX_DAILY_LOSS, CAPITAL)
            print(f"Today's closed trades: {summary['closed_trades']} | Today's P/L: Rs {summary['pnl']:.2f}")

            if not allowed:
                write_heartbeat("blocked", reason=reason)
                print(f"Bot waiting: {reason}")
                # Being outside the entry window is normal. Keep the service
                # alive so systemd does not restart it continuously, and allow
                # the next trading session to begin without manual intervention.
                time.sleep(min(60, RESCAN_DELAY_SECONDS))
                continue

            results = scan_market()
            print_results(results)
            write_heartbeat("scanned", candidates=len(results))
            admitted, rejected = discover()
            print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

            if not admitted:
                print("No HIGH-CONVICTION fundamental candidate. No paper trade will be created.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            admitted_symbols = {x["symbol"] for x in admitted}
            eligible_market = [x for x in results if x.get("symbol", "").upper() in admitted_symbols]
            candidate = select_best_candidate(eligible_market, MINIMUM_SCORE)
            if not candidate:
                print("High-conviction fundamental candidate exists, but no qualifying market signal.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print(f"HIGH-CONVICTION PAPER CANDIDATE: {candidate['symbol']} | Score {candidate['score']}/100")
            option_type = "CE" if candidate["signal"] == "BUY CE" else "PE"
            contract_probe = resolve_option_contract(candidate["symbol"], candidate["close"], candidate["signal"])
            if contract_probe.get("status") != "CONTRACT VALID":
                print("Options contract/LTP validation rejected candidate:", contract_probe)
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            gate_candidate = {
                "symbol": candidate["symbol"],
                "option_type": option_type,
                "expiry": contract_probe.get("expiry", ""),
                "ltp": contract_probe.get("ltp", 0),
                "exchange": contract_probe.get("exchange", "NFO"),
                "token": contract_probe.get("token", ""),
                "trend_score": candidate.get("score", 0),
                "momentum_score": candidate.get("score", 0),
                "volume_score": candidate.get("volume_ratio", 0),
                "vwap_score": candidate.get("score", 0),
                "index_confirmation": 8 if candidate.get("trend") else 0,
                "oi_score": 0,
                "oi_change_score": 0,
                "iv_score": 0,
                "liquidity_score": 0,
                "volatility_score": 0,
                "structure_score": 0,
                "news_confirmation": 0,
                "event_risk_penalty": 0,
                "spread_pct": 0,
                "slippage_pct": 0,
            }

            options_result = evaluate_option_candidate(gate_candidate)
            gate = options_result.get("options_gate", {})
            print(f"OPTIONS GATE: {options_result.get('options_score', 0)}/100 | {gate.get('decision', 'NO TRADE')}")
            if not options_result.get("paper_trade_candidate"):
                print("Options gate rejected candidate:", gate.get("reasons", []))
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            write_heartbeat("creating_trade", symbol=candidate["symbol"])
            trade = create_trade(candidate["symbol"], candidate["close"], candidate["signal"], CAPITAL)
            if trade.get("status") != "PAPER TRADE ACTIVE":
                print("Trade was not created:", trade)
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            send_entry_alert(trade)
            write_heartbeat("monitoring", symbol=trade.get("symbol"), contract=trade.get("contract"))
            result = run_monitor(trade)
            if result is None:
                write_heartbeat("stopped")
                print("Bot stopped manually.")
                return
            print("Trade cycle complete. Returning to scanner.")
            write_heartbeat("trade_complete", symbol=trade.get("symbol"))
            time.sleep(RESCAN_DELAY_SECONDS)
    finally:
        write_heartbeat("stopped")
        release_single_instance(lock)


if __name__ == "__main__":
    main()
