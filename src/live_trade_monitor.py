import time


def run_monitor(
    trade,
    poll_seconds=3,
    get_ltp=None,
    notify=True,
    log_path="data/trades.csv",
    persist_outcome=True,
):
    """Monitor one paper trade without importing broker/Telegram modules at collection time.

    ``persist_outcome`` allows isolated lifecycle tests to avoid writing
    synthetic outcomes into the production learning database.
    """
    # Lazy imports keep unit-test collection offline and prevent optional broker
    # integrations from becoming import-time dependencies.
    if get_ltp is None:
        from src.live_option_price import get_option_ltp
        get_ltp = get_option_ltp
    from src.risk_manager import should_force_exit
    from src.telegram_alert import send_exit_alert, send_alert
    from src.trade_logger import log_closed_trade
    from src.trading_risk_manager import TradingRiskManager
    from src.trade_monitor import monitor_trade
    from src.production_guard import write_heartbeat

    print("=" * 60)
    print("PEREZ AI LIVE PAPER-TRADE MONITOR")
    print("=" * 60)
    consecutive_errors = 0
    last_health_alert = 0.0

    while True:
        try:
            write_heartbeat("monitoring", symbol=trade.get("symbol"), contract=trade.get("contract"), strategy=trade.get("strategy", "CORE"))
            ltp = get_ltp(trade["exchange"], trade["contract"], trade["token"])
            if ltp is None:
                write_heartbeat("monitoring_ltp_unavailable", symbol=trade.get("symbol"), contract=trade.get("contract"), strategy=trade.get("strategy", "CORE"))
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

                # Persist closed outcome into canonical learning memory.
                # Observational only; never changes trading or risk decisions.
                if persist_outcome:
                    try:
                        from src.outcome_recorder import record_closed_outcome
                        outcome_written = record_closed_outcome(trade, result)
                        print(
                            'OUTCOME MEMORY:',
                            'RECORDED' if outcome_written else 'ALREADY_RECORDED',
                            f"trade_id={trade.get('trade_id', '')}",
                        )
                    except Exception as outcome_error:
                        print('OUTCOME MEMORY ERROR:', outcome_error)
                else:
                    print("OUTCOME MEMORY: SKIPPED (isolated lifecycle test)")

                # Production risk bookkeeping is skipped for isolated
                # lifecycle tests. Production defaults to persist_outcome=True.
                if persist_outcome:
                                trade_id = trade.get("trade_id")
                                if trade_id:
                                    risk_manager = TradingRiskManager()

                                    try:
                                        pnl = float(result.get("pnl", 0.0) or 0.0)
                                    except (TypeError, ValueError):
                                        pnl = 0.0

                                    exit_reason = str(
                                        result.get("exit_reason", "")
                                    ).upper()

                                    stop_loss_trigger = (
                                        pnl < 0.0
                                        and exit_reason in {"STOP_LOSS", "TRAILING_STOP"}
                                    )

                                    if stop_loss_trigger:
                                        _, sl_reason = risk_manager.record_stop_loss(trade_id)
                                        print(f"RISK MANAGER: SL update | {sl_reason}")

                                    risk_manager.record_trade_result(
                                        trade_id,
                                        pnl,
                                        stop_loss=stop_loss_trigger,
                                    )

                                    rs = risk_manager.status()
                                    print(
                                        f"RISK MANAGER: loss_streak="
                                        f"{rs['consecutive_losses']} | "
                                        f"breaker={rs['circuit_breaker_active']}"
                                    )

                else:
                    print("RISK MANAGER: SKIPPED (isolated lifecycle test)")
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
            write_heartbeat("monitoring_error", symbol=trade.get("symbol"), contract=trade.get("contract"), strategy=trade.get("strategy", "CORE"), error=str(error))
            consecutive_errors += 1
            print("Monitor error:", error)
            if consecutive_errors >= 3 and time.time() - last_health_alert > 300:
                send_alert(
                    f"PEREZ AI HEALTH ERROR\n\nContract: {trade.get('contract', 'UNKNOWN')}\n"
                    f"Error: {error}\nConsecutive failures: {consecutive_errors}"
                )
                last_health_alert = time.time()
            time.sleep(poll_seconds)
