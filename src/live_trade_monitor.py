import time

from src.live_option_price import get_option_ltp
from src.risk_manager import should_force_exit
from src.telegram_alert import send_exit_alert, send_alert
from src.trade_logger import log_closed_trade
from src.trade_monitor import monitor_trade

# Public test/runtime seam. Keeping this name lets the monitor be driven by a
# deterministic paper quote source without patching broker modules.
get_ltp = get_option_ltp


def run_monitor(trade, poll_seconds=3, get_ltp=None, notify=True, log_path="data/trades.csv"):
    """Monitor one paper trade and persist its outcome exactly once on close.

    Outcome learning belongs at the closure boundary, not only in the caller,
    so every closed paper trade is learnable even if a higher-level caller
    exits immediately afterwards. ``ai_memory.remember_outcome`` is
    idempotent by trade_id, so main.py may safely perform a second reconciliation.
    """
    quote_fn = get_ltp or globals()["get_ltp"]
    print("=" * 60)
    print("PEREZ AI LIVE PAPER-TRADE MONITOR")
    print("=" * 60)
    consecutive_errors = 0
    last_health_alert = 0.0

    while True:
        try:
            ltp = quote_fn(trade["exchange"], trade["contract"], trade["token"])
            if ltp is None:
                consecutive_errors += 1
                print(f"LTP unavailable; retrying ({consecutive_errors})")
                if consecutive_errors >= 3 and time.time() - last_health_alert > 300:
                    send_alert(f"PEREZ AI HEALTH WARNING\n\nLTP unavailable for {trade['contract']}\nConsecutive failures: {consecutive_errors}\nPaper trading remains active; no live order is placed.")
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
                # Closure is the authoritative learning boundary. The memory
                # layer rejects missing trade IDs and deduplicates retries.
                try:
                    from src.ai_memory import remember_outcome
                    learning = remember_outcome(trade, result, regime=trade.get("regime", "unknown"))
                    print(
                        "AI MEMORY: outcome "
                        f"{'STORED' if learning.get('stored') else 'ALREADY_STORED'} "
                        f"trade_id={learning.get('trade_id')}"
                    )
                except Exception as exc:
                    # Never turn a successful paper exit into a false failure;
                    # main.py can retry the same idempotent write.
                    print(f"AI MEMORY WARNING — outcome reconciliation pending: {exc}")
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
                send_alert(f"PEREZ AI HEALTH ERROR\n\nContract: {trade.get('contract', 'UNKNOWN')}\nError: {error}\nConsecutive failures: {consecutive_errors}")
                last_health_alert = time.time()
            time.sleep(poll_seconds)
