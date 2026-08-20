from datetime import datetime


def monitor_trade(trade, current_price):
    """Monitor a paper trade without requiring optional partial-booking fields."""
    entry = float(trade["entry"])
    current_price = float(current_price)

    # Backward-compatible quantity handling. Older paper trades may not have
    # remaining_quantity; fall back to the original quantity and persist it.
    if trade.get("remaining_quantity") is None:
        original_quantity = trade.get("quantity", trade.get("qty", 0))
        if not original_quantity:
            raise KeyError("Trade is missing quantity/qty")
        trade["remaining_quantity"] = int(original_quantity)

    quantity = int(trade["remaining_quantity"])
    trade.setdefault("partial_booked", False)
    trade.setdefault("realized_pnl", 0.0)

    initial_stop = float(trade.get("initial_stop_loss", trade["stop_loss"]))
    stop_loss = float(trade["stop_loss"])
    target1 = float(trade.get("target1", trade.get("target", current_price)))
    target2 = float(trade.get("target2", trade.get("target", target1)))

    target1_hit = False

    # Target 1: partial booking is optional and only applies when configured.
    if not trade["partial_booked"] and "target1" in trade and current_price >= target1:
        trade["partial_booked"] = True
        booked_qty = quantity // 2
        if booked_qty > 0:
            realized = round((target1 - entry) * booked_qty, 2)
            trade["realized_pnl"] = round(trade.get("realized_pnl", 0.0) + realized, 2)
            trade["remaining_quantity"] = quantity - booked_qty
            quantity = trade["remaining_quantity"]
            stop_loss = entry
            trade["stop_loss"] = stop_loss
            target1_hit = True
            print(">>> TARGET 1 HIT - 50% BOOKED")
            print(f">>> Booked Qty: {booked_qty}")
            print(f">>> Remaining Qty: {quantity}")
            print(f">>> Realized P/L: {trade['realized_pnl']}")
            print(f">>> SL moved to Entry: {entry}")

    risk = entry - initial_stop
    if risk > 0 and not target1_hit:
        if current_price >= entry + risk:
            stop_loss = max(stop_loss, entry)
        if current_price >= entry + (2 * risk):
            stop_loss = max(stop_loss, current_price - risk)

    trade["stop_loss"] = round(stop_loss, 2)

    unrealized = round((current_price - entry) * quantity, 2)
    realized = round(trade.get("realized_pnl", 0.0), 2)
    pnl = round(realized + unrealized, 2)
    pnl_percent = round(((current_price - entry) / entry) * 100, 2) if entry else 0.0

    status = "RUNNING"
    exit_reason = ""
    if current_price >= target2:
        status = "TARGET 2 HIT"
        exit_reason = "TARGET2"
    elif current_price <= stop_loss:
        status = "STOP LOSS HIT"
        exit_reason = "TRAILING_STOP"

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract": trade["contract"],
        "entry": entry,
        "current": current_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "target": target2,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "status": status,
        "exit_reason": exit_reason,
        "target1_hit": target1_hit,
        "closed": status != "RUNNING",
    }
