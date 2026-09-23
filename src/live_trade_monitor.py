import time


def run_monitor(
    trade,
    poll_seconds=3,
    get_ltp=None,
    notify=True,
    log_path="data/trades.csv",
    persist_outcome=True,
):
    """Monitor one paper trade and persist a complete lifecycle timeline."""
    if get_ltp is None:
        from src.live_option_price import get_option_ltp
        get_ltp = get_option_ltp
    from src.risk_manager import should_force_exit
    from src.telegram_alert import send_exit_alert, send_alert
    from src.trade_logger import log_closed_trade
    from src.trading_risk_manager import TradingRiskManager
    from src.trade_monitor import monitor_trade
    from src.production_guard import write_heartbeat
    from src.paper_trade_lifecycle import now_utc, record_event, elapsed_seconds
    from src.time_stop import evaluate_time_stop, TRAIL_TO_BREAKEVEN, TIME_STOP_EXIT
    from src.active_position_guard import release_contract

    print("=" * 60)
    print("PEREZ AI LIVE PAPER-TRADE MONITOR")
    print("=" * 60)
    consecutive_errors = 0
    last_health_alert = 0.0

    # Legacy/synthetic callers may not have lifecycle fields.
    trade.setdefault("opened_at", "")
    trade.setdefault("detected_at", "")
    trade.setdefault("target1_at", "")
    trade.setdefault("closed_at", "")

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
            was_partial = bool(trade.get("partial_booked"))
            result = monitor_trade(trade, ltp)

            # TimeStop is evaluated after normal target/SL handling so it
            # cannot override a legitimate same-tick target or stop event.
            if not result.get("closed") and trade.get("opened_at"):
                time_stop_action = evaluate_time_stop(
                    trade.get("opened_at"),
                    result.get("time") or now_utc(),
                    float(trade.get("target1", 0) or 0),
                    float(ltp),
                    float(trade.get("entry", 0) or 0),
                    target1_reached=bool(result.get("target1_hit")),
                )
                if time_stop_action == TRAIL_TO_BREAKEVEN and not trade.get("time_stop_breakeven"):
                    trade["time_stop_breakeven"] = True
                    record_event(
                        trade,
                        "TRAIL_TO_BREAKEVEN",
                        ts=now_utc(),
                        price=float(ltp),
                        hold_duration_minutes=15,
                    )
                elif time_stop_action == TIME_STOP_EXIT:
                    exit_price = float(ltp)
                    remaining_qty = int(result.get("remaining_quantity", result.get("quantity", 0)) or 0)
                    entry_price = float(trade["entry"])
                    realized = float(result.get("realized_pnl", 0.0) or 0.0)
                    realized = round(realized + (exit_price - entry_price) * remaining_qty, 2)
                    initial_exposure = max(
                        entry_price * int(result.get("original_quantity", trade.get("quantity", 1)) or 1),
                        1.0,
                    )
                    result["status"] = "TIME STOP EXIT"
                    result["exit_reason"] = "TIME_STOP_EXIT"
                    result["exit_price"] = exit_price
                    result["remaining_quantity"] = 0
                    result["quantity"] = 0
                    result["realized_pnl"] = realized
                    result["unrealized_pnl"] = 0.0
                    result["pnl"] = realized
                    result["pnl_percent"] = round(realized / initial_exposure * 100.0, 2)
                    result["closed"] = True
                    trade["remaining_quantity"] = 0
                    release_contract(trade["contract"], trade.get("trade_id"))
                    record_event(
                        trade,
                        "TIME_STOP_EXIT",
                        ts=now_utc(),
                        exit_price=exit_price,
                        pnl=realized,
                    )

            # monitor_trade owns normal SL/target exits. Capture the T1 event
            # once, immediately after the state transition.
            if result.get("target1_hit") and not was_partial and not trade.get("target1_at"):
                trade["target1_at"] = now_utc()
                record_event(
                    trade,
                    "TARGET1_PARTIAL",
                    ts=trade["target1_at"],
                    price=float(result.get("target1") or trade.get("target1") or ltp),
                    booked_quantity=int(result.get("original_quantity", 0) // 2),
                    remaining_quantity=int(result.get("remaining_quantity", 0)),
                    realized_pnl=float(result.get("realized_pnl", 0.0) or 0.0),
                )

            if not result["closed"] and should_force_exit():
                # Market-close exit must be fully accounted for before outcome
                # persistence; older code marked closed without realizing P/L.
                exit_price = float(ltp)
                remaining_qty = int(result.get("remaining_quantity", result.get("quantity", 0)) or 0)
                entry_price = float(trade["entry"])
                realized = float(result.get("realized_pnl", 0.0) or 0.0)
                realized = round(realized + (exit_price - entry_price) * remaining_qty, 2)
                initial_exposure = max(entry_price * int(result.get("original_quantity", trade.get("quantity", 1)) or 1), 1.0)
                result["status"] = "MARKET CLOSE EXIT"
                result["exit_reason"] = "MARKET_CLOSE"
                result["exit_price"] = exit_price
                result["remaining_quantity"] = 0
                result["quantity"] = 0
                result["realized_pnl"] = realized
                result["unrealized_pnl"] = 0.0
                result["pnl"] = realized
                result["pnl_percent"] = round(realized / initial_exposure * 100.0, 2)
                result["closed"] = True
                trade["remaining_quantity"] = 0
                release_contract(trade["contract"], trade.get("trade_id"))

            print("-" * 60)
            print("Trade ID :", trade.get("trade_id", ""))
            print("Contract :", result["contract"])
            print("Entry    :", result["entry"])
            print("LTP      :", result["current"])
            print("P/L      :", result["pnl"])
            print("P/L %    :", result["pnl_percent"])
            print("Status   :", result["status"])

            if result["closed"]:
                trade["closed_at"] = now_utc()
                result["closed_at"] = trade["closed_at"]
                result["detected_at"] = trade.get("detected_at", "")
                result["opened_at"] = trade.get("opened_at", "")
                result["target1_at"] = trade.get("target1_at", "")
                result["detection_to_open_seconds"] = elapsed_seconds(result["detected_at"], result["opened_at"])
                result["open_to_target1_seconds"] = elapsed_seconds(result["opened_at"], result["target1_at"])
                result["open_to_close_seconds"] = elapsed_seconds(result["opened_at"], result["closed_at"])
                result["detection_to_close_seconds"] = elapsed_seconds(result["detected_at"], result["closed_at"])

                record_event(
                    trade,
                    "CLOSE",
                    ts=trade["closed_at"],
                    exit_price=float(result.get("exit_price") or result.get("current") or 0.0),
                    quantity=0,
                    pnl=float(result.get("pnl", 0.0) or 0.0),
                    pnl_percent=float(result.get("pnl_percent", 0.0) or 0.0),
                    exit_reason=result.get("exit_reason", ""),
                    detection_to_open_seconds=result.get("detection_to_open_seconds"),
                    open_to_target1_seconds=result.get("open_to_target1_seconds"),
                    open_to_close_seconds=result.get("open_to_close_seconds"),
                    detection_to_close_seconds=result.get("detection_to_close_seconds"),
                )

                record = log_closed_trade(trade, result, log_path)

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

                if persist_outcome and trade.get("learning_candidate"):
                    try:
                        from src.adaptive_learning import remember_candidate, resolve_outcome
                        candidate = dict(trade["learning_candidate"])
                        event_key = "trade:" + str(trade.get("trade_id", ""))
                        remember_candidate(candidate, event_key)
                        resolved = resolve_outcome(event_key=event_key, candidate=candidate, pnl=result.get("pnl", 0.0), pnl_percent=result.get("pnl_percent", 0.0), mfe=result.get("mfe"), mae=result.get("mae"), exit_reason=result.get("exit_reason", ""))
                        print("ADAPTIVE LEARNING:", "RESOLVED" if resolved else "NOT_RESOLVED", event_key)
                    except Exception as exc:
                        print("ADAPTIVE LEARNING ERROR:", exc)

                if persist_outcome:
                    trade_id = trade.get("trade_id")
                    risk_identity = trade.get("lineage_id") or trade_id
                    if risk_identity:
                        risk_manager = TradingRiskManager()
                        try:
                            pnl = float(result.get("pnl", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            pnl = 0.0
                        exit_reason = str(result.get("exit_reason", "")).upper()
                        stop_loss_trigger = pnl < 0.0 and exit_reason in {"STOP_LOSS", "TRAILING_STOP"}
                        if stop_loss_trigger:
                            _, sl_reason = risk_manager.record_stop_loss(risk_identity)
                            print(f"RISK MANAGER: SL update | {sl_reason}")
                        risk_manager.record_trade_result(risk_identity, pnl, stop_loss=stop_loss_trigger)
                        rs = risk_manager.status()
                        print(f"RISK MANAGER: loss_streak={rs['consecutive_losses']} | breaker={rs['circuit_breaker_active']}")
                else:
                    print("RISK MANAGER: SKIPPED (isolated lifecycle test)")
                if notify:
                    send_exit_alert(trade, result)
                print(f"TRADE CLOSED: {result['exit_reason']} | trade_id={trade.get('trade_id', '')}")
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
