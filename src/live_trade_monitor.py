import time


def run_monitor(trade, poll_seconds=3, get_ltp=None, notify=True, log_path="data/trades.csv"):
    """Monitor one paper trade without importing broker/Telegram modules at collection time."""
    # Lazy imports keep unit-test collection offline and prevent optional broker
    # integrations from becoming import-time dependencies.
    if get_ltp is None:
        from src.live_option_price import get_option_ltp
        get_ltp = get_option_ltp
    from src.risk_manager import should_force_exit
    from src.telegram_alert import send_exit_alert, send_alert
    from src.trade_logger import log_closed_trade
    from src.trade_monitor import monitor_trade

    print("=" * 60)
    print("PEREZ AI LIVE PAPER-TRADE MONITOR")
    print("=" * 60)
    consecutive_errors = 0
    last_health_alert = 0.0

    while True:
        try:
            ltp = get_ltp(trade["exchange"], trade["contract"], trade["token"])
            if ltp is None:
                consecutive_errors += 1
                print(f"LTP unavailable; retrying ({consecutive_errors})")
                if consecutive_errors >= 3 and time.time() - last_health_alert > 300:
                    send_alert(
                        f"PEREZ AI HEALTH WARNING\n\nLTP unavailable for {trade['contract']}\n"
                        f"Consecutive failures: {consecutive_errors}\n"
                        "Paper trading remains active; no live order is placed."
                    )
                    last_health_alert = time.time()
                time.sleep(poll_seconds)
                continue

            consecutive_errors = 0
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
            consecutive_errors += 1
            print("Monitor error:", error)
            if consecutive_errors >= 3 and time.time() - last_health_alert > 300:
                send_alert(
                    f"PEREZ AI HEALTH ERROR\n\nContract: {trade.get('contract', 'UNKNOWN')}\n"
                    f"Error: {error}\nConsecutive failures: {consecutive_errors}"
                )
                last_health_alert = time.time()
            time.sleep(poll_seconds)
