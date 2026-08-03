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


if __name__ == "__main__":

    contract = {
        "symbol": "AXISBANK04AUG261240CE",
        "token": "XXXXX"
    }

    print(create_paper_trade(contract, 20, 5000))
