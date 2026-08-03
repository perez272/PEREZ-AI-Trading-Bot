import math

def select_option(symbol, signal, spot_price, capital=5000):

    if signal == "BUY CE":
        direction = "CE"
    elif signal == "BUY PE":
        direction = "PE"
    else:
        return None

    # Approximate ATM strike
    strike = round(spot_price / 10) * 10

    # Placeholder option premium estimate
    # Real option chain will replace this in next step
    premium = max(10, abs(spot_price * 0.02))

    lot_size = {
        "NIFTY": 75,
        "BANKNIFTY": 30,
        "AXISBANK": 625,
        "HDFCBANK": 550,
        "ICICIBANK": 700
    }.get(symbol, 1)

    quantity = math.floor(capital / premium)

    if quantity < 1:
        return {
            "status": "NO TRADE",
            "reason": "Premium too high"
        }

    return {
        "symbol": symbol,
        "type": direction,
        "strike": strike,
        "premium": round(premium,2),
        "lot_size": lot_size,
        "quantity": quantity,
        "investment": round(quantity * premium,2)
    }
