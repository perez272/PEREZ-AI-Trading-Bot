from datetime import datetime


def monitor_trade(trade, current_price):
    """Evaluate one paper trade with consistent partial-exit accounting."""
    entry = float(trade["entry"])
    current_price = float(current_price)
    raw_quantity = trade.get("quantity", trade.get("remaining_quantity"))
    if raw_quantity is None:
        raise ValueError("Trade is missing required quantity/remaining_quantity")
    original_quantity = int(trade.get("original_quantity", raw_quantity))
    if original_quantity < 1:
        raise ValueError(f"Invalid original quantity: {original_quantity!r}")
    remaining = int(trade.get("remaining_quantity", raw_quantity))
    if remaining < 0 or remaining > original_quantity:
        raise ValueError(f"Invalid remaining_quantity: {remaining}; original={original_quantity}")
    trade["original_quantity"] = original_quantity
    trade["remaining_quantity"] = remaining
    trade.setdefault("partial_booked", False)
    trade.setdefault("realized_pnl", 0.0)

    initial_stop = float(trade.get("initial_stop_loss", trade["stop_loss"]))
    stop_loss = float(trade["stop_loss"])
    target1 = float(trade["target1"])
    target2 = float(trade["target2"])
    target1_hit = False
    trail_pct = float(trade.get("trailing_stop_pct", 15.0))
    high_watermark = max(float(trade.get("high_watermark", entry)), current_price)
    trade["high_watermark"] = round(high_watermark, 2)

    if not trade["partial_booked"] and current_price >= target1:
        booked_qty = remaining // 2
        if booked_qty > 0:
            trade["partial_booked"] = True
            trade["realized_pnl"] = round(float(trade["realized_pnl"]) + (target1 - entry) * booked_qty, 2)
            remaining -= booked_qty
            trade["remaining_quantity"] = remaining
            stop_loss = entry
            trade["stop_loss"] = stop_loss
            target1_hit = True
            print(">>> TARGET 1 HIT - 50% BOOKED")
            print(f">>> Booked Qty: {booked_qty}")
            print(f">>> Remaining Qty: {remaining}")
            print(f">>> Realized P/L: {trade['realized_pnl']}")

    risk = entry - initial_stop
    if risk > 0 and not trade.get("partial_booked", False):
        if current_price >= entry + risk:
            stop_loss = max(stop_loss, entry)
        if current_price >= entry + 2 * risk:
            stop_loss = max(stop_loss, current_price - risk)

    if trade.get("partial_booked", False) and trail_pct > 0:
        trailing_stop = high_watermark * (1.0 - trail_pct / 100.0)
        stop_loss = max(stop_loss, trailing_stop)

    trade["stop_loss"] = round(stop_loss, 2)

    unrealized = round((current_price - entry) * remaining, 2)
    realized = round(float(trade.get("realized_pnl", 0.0)), 2)
    pnl = round(realized + unrealized, 2)
    initial_exposure = max(entry * original_quantity, 1.0)
    pnl_percent = round((pnl / initial_exposure) * 100, 2)

    status = "RUNNING"
    exit_reason = ""
    if current_price <= stop_loss:
        status, exit_reason = "STOP LOSS HIT", "TRAILING_STOP"

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract": trade["contract"], "entry": entry, "current": current_price,
        "quantity": remaining, "original_quantity": original_quantity,
        "remaining_quantity": remaining, "stop_loss": stop_loss, "target": target2,
        "high_watermark": high_watermark, "trailing_stop_pct": trail_pct,
        "realized_pnl": realized, "unrealized_pnl": unrealized, "pnl": pnl,
        "pnl_percent": pnl_percent, "status": status, "exit_reason": exit_reason,
        "target1_hit": bool(trade.get("partial_booked")), "closed": status != "RUNNING",
    }
