from datetime import datetime


def create_paper_trade(contract, ltp, capital=5000):

    quantity = int(capital / ltp)

    if quantity <= 0:
        return {
            "status": "NO TRADE",
            "reason": "Premium too high"
        }

    investment = round(quantity * ltp, 2)

    stop_loss = round(ltp * 0.98, 2)
    target = round(ltp * 1.07, 2)

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": contract["symbol"],
        "token": contract["token"],
        "entry": ltp,
        "quantity": quantity,
        "investment": investment,
        "stop_loss": stop_loss,
        "target": target,
        "status": "OPEN"
    }


def check_paper_exit(trade, current_ltp):

    if trade.get("status") != "OPEN":
        return trade

    entry = float(trade["entry"])
    quantity = int(trade["quantity"])
    stop_loss = float(trade["stop_loss"])
    target = float(trade["target"])
    current_ltp = float(current_ltp)

    exit_reason = None

    if current_ltp <= stop_loss:
        exit_reason = "STOP_LOSS"

    elif current_ltp >= target:
        exit_reason = "TARGET"

    if exit_reason is None:
        trade["current_ltp"] = current_ltp
        trade["unrealized_pnl"] = round(
            (current_ltp - entry) * quantity, 2
        )
        return trade

    pnl = round(
        (current_ltp - entry) * quantity, 2
    )

    trade["exit_time"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    trade["exit"] = current_ltp
    trade["pnl"] = pnl
    trade["exit_reason"] = exit_reason
    trade["status"] = "CLOSED"

    return trade


if __name__ == "__main__":

    contract = {
        "symbol": "AXISBANK04AUG261240CE",
        "token": "XXXXX"
    }

    trade = create_paper_trade(contract, 20, 5000)

    print("OPEN:")
    print(trade)

    print()
    print("AFTER TARGET TEST:")
    print(check_paper_exit(trade, trade["target"]))
