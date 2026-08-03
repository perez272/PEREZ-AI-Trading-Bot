from datetime import datetime


def monitor_trade(trade, current_price):
    entry = float(trade["entry"])
    quantity = int(trade["quantity"])
    current_price = float(current_price)

    pnl = round((current_price - entry) * quantity, 2)
    pnl_percent = round(((current_price - entry) / entry) * 100, 2)

    status = "RUNNING"
    exit_reason = ""

    if current_price >= float(trade["target"]):
        status = "TARGET HIT"
        exit_reason = "TARGET"
    elif current_price <= float(trade["stop_loss"]):
        status = "STOP LOSS HIT"
        exit_reason = "STOP_LOSS"

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contract": trade["contract"],
        "entry": entry,
        "current": current_price,
        "quantity": quantity,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "status": status,
        "exit_reason": exit_reason,
        "closed": status != "RUNNING",
    }
