import time

from src.live_option_price import get_option_ltp
from src.risk_manager import should_force_exit
from src.telegram_alert import send_exit_alert
from src.trade_logger import log_closed_trade
from src.trade_monitor import monitor_trade


def run_monitor(
    trade,
    poll_seconds=5,
    get_ltp=get_option_ltp,
    notify=True,
    log_path="data/trades.csv",
):
    print("=" * 60)
    print("PEREZ AI LIVE PAPER-TRADE MONITOR")
    print("=" * 60)

    while True:
        try:
            ltp = get_ltp(
                trade["exchange"],
                trade["contract"],
                trade["token"],
            )

            if ltp is None:
                print("LTP unavailable; retrying.")
                time.sleep(poll_seconds)
                continue

            result = monitor_trade(trade, ltp)

            if not result["closed"] and should_force_exit():
                result["status"] = "MARKET CLOSE EXIT"
                result["exit_reason"] = "MARKET_CLOSE"
                result["closed"] = True

            print("-" * 60)
            print("Contract :", result["contract"])
            print("Entry    :", result["entry"])
            print("LTP      :", result["current"])
            print("P/L      :", result["pnl"])
            print("P/L %    :", result["pnl_percent"])
            print("Status   :", result["status"])

            if result["closed"]:
                record = log_closed_trade(trade, result, log_path)

                if notify:
                    send_exit_alert(trade, result)

                print(f"TRADE CLOSED: {result['exit_reason']}")
                print(f"Saved to: {log_path}")
                return {**result, "record": record}

            time.sleep(poll_seconds)

        except KeyboardInterrupt:
            print("Monitor stopped manually.")
            return None
        except Exception as error:
            print("Monitor error:", error)
            time.sleep(poll_seconds)
