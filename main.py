import time

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade


CAPITAL = 50000
MINIMUM_SCORE = 55
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 300.0
RESCAN_DELAY_SECONDS = 300


def main():
    print("=" * 60)
    print("PEREZ AI PAPER-TRADING BOT")
    print("Paper mode only — no real orders are placed.")
    print("=" * 60)

    while True:
        allowed, reason, summary = can_open_new_trade(
            MAX_TRADES_PER_DAY,
            MAX_DAILY_LOSS,
        )

        print(
            f"Today's closed trades: {summary['closed_trades']} | "
            f"Today's P/L: Rs {summary['pnl']:.2f}"
        )

        if not allowed:
            print(f"Bot stopped: {reason}")
            return

        results = scan_market()
        print_results(results)

        candidate = select_best_candidate(results, MINIMUM_SCORE)
        if not candidate:
            print(f"No qualifying signal. Rescanning in {RESCAN_DELAY_SECONDS} seconds.")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        trade = create_trade(
            candidate["symbol"],
            candidate["close"],
            candidate["signal"],
            CAPITAL,
        )

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
