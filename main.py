import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate
from src.options_scanner import scan_top_options, select_best_option
from src.risk_manager import can_open_new_trade, is_entry_window, now_ist
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade
from src.high_conviction_discovery import discover
from src.upgrade_config import (
    RESCAN_DELAY_SECONDS,
    MINIMUM_SCORE,
    MAX_TRADES_PER_DAY,
    MAX_DAILY_LOSS,
    OPTIONS_MIN_SCORE,
)

CAPITAL = 50000


def wait_for_0915_ist():
    tz = ZoneInfo("Asia/Kolkata")
    start = dt_time(9, 15)
    while True:
        now = datetime.now(tz)
        if now.time() >= start:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR 09:15 IST — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def main():
    wait_for_0915_ist()
    print("=" * 72)
    print("PEREZ AI PAPER-TRADING BOT — UPGRADED")
    print("Paper mode only — no real orders are placed.")
    print("09:15 IST — fresh-data scanning enabled.")
    print(f"Market score threshold: {MINIMUM_SCORE} | Options threshold: {OPTIONS_MIN_SCORE}")
    print(f"Rescan interval: {RESCAN_DELAY_SECONDS}s")
    print("SEPARATE SCANS: TOP SHARES -> TOP OPTIONS")
    print("=" * 72)

    while True:
        if not is_entry_window():
            current = now_ist()
            print(
                f"Waiting — outside entry window: {current.strftime('%H:%M:%S')} IST | "
                "entry window 09:30-14:45 IST"
            )
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        allowed, reason, summary = can_open_new_trade(
            MAX_TRADES_PER_DAY, MAX_DAILY_LOSS, CAPITAL
        )
        print(
            f"Today's closed trades: {summary['closed_trades']} | "
            f"Today's P/L: Rs {summary['pnl']:.2f}"
        )
        if not allowed:
            print(f"Trading paused by risk gate: {reason}")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        # Stage 1: scan and rank underlying shares/indices only.
        share_results = scan_market()
        print_results(share_results)

        # Stage 2: separately resolve/enrich/rank only the strongest option
        # contracts implied by the top-share signals. This keeps the NFO scan
        # small and auditable instead of scanning the entire option master.
        option_results = scan_top_options(share_results, max_underlyings=10)
        best_option = select_best_option(option_results)
        if best_option:
            print(
                f"BEST OPTION: {best_option.get('symbol')} {best_option.get('option_type')} "
                f"score={best_option.get('options_score', 0)}/100 "
                f"paper={best_option.get('paper_trade_candidate', False)}"
            )
        else:
            print("BEST OPTION: none passed the options gate")

        admitted, rejected = discover()
        print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

        if not admitted:
            print("No HIGH-CONVICTION fundamental candidate. No paper trade will be created.")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        admitted_symbols = {x["symbol"] for x in admitted}
        eligible_market = [x for x in share_results if x.get("symbol", "").upper() in admitted_symbols]
        candidate = select_best_candidate(eligible_market, MINIMUM_SCORE)
        if not candidate:
            print("High-conviction fundamental candidate exists, but no qualifying market signal.")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        print(f"HIGH-CONVICTION PAPER SHARE CANDIDATE: {candidate['symbol']} | Score {candidate['score']}/100")

        matching_options = [
            x for x in option_results
            if x.get("symbol", "").upper() == candidate["symbol"].upper()
            and x.get("option_type", "").upper() == ("CE" if candidate["signal"] == "BUY CE" else "PE")
        ]
        if not matching_options:
            print("No separately scanned option contract for the selected share candidate.")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        options_result = max(matching_options, key=lambda x: x.get("options_score", 0))
        gate = options_result.get("options_gate", {})
        print(
            f"OPTIONS GATE: {options_result.get('options_score', 0)}/100 | "
            f"{gate.get('decision', 'NO TRADE')} | "
            f"{candidate['symbol']} {options_result.get('option_type', '')}"
        )
        if options_result.get("options_score", 0) < OPTIONS_MIN_SCORE or not options_result.get("paper_trade_candidate"):
            print("Options gate rejected candidate:", gate.get("reasons", []))
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        trade = create_trade(candidate["symbol"], candidate["close"], candidate["signal"], CAPITAL)
        if trade.get("status") != "PAPER TRADE ACTIVE":
            print("Trade was not created:", trade)
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        send_entry_alert(trade)
        result = run_monitor(trade)
        if result is None:
            print("Bot stopped manually.")
            return
        print("Trade cycle complete. Returning to scanner.")
        time.sleep(RESCAN_DELAY_SECONDS)


if __name__ == "__main__":
    main()
