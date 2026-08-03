from src.contract_selector import select_contract
from src.live_option_price import get_option_ltp


def create_trade(symbol, spot, signal, capital=5000):
    if signal not in ("BUY CE", "BUY PE"):
        return {"status": "NO TRADE", "reason": "No valid CE/PE signal"}

    option_type = "CE" if signal == "BUY CE" else "PE"
    contract = select_contract(symbol, spot, option_type)

    if not contract or contract.get("status") == "NO CONTRACT":
        return {"status": "NO CONTRACT"}

    ltp = get_option_ltp(
        contract["exchange"],
        contract["symbol"],
        contract["token"],
    )

    if not ltp or ltp <= 0:
        return {"status": "NO LTP"}

    lot_size = int(float(contract["lotsize"]))
    lots = int(capital // (ltp * lot_size))

    if lots < 1:
        return {
            "status": "LOW CAPITAL",
            "reason": f"One lot needs Rs {ltp * lot_size:.2f}",
        }

    quantity = lots * lot_size
    investment = round(quantity * ltp, 2)

    return {
        "symbol": symbol,
        "signal": signal,
        "contract": contract["symbol"],
        "exchange": contract["exchange"],
        "token": contract["token"],
        "entry": float(ltp),
        "quantity": quantity,
        "lots": lots,
        "investment": investment,
        "stop_loss": round(float(ltp) * 0.98, 2),
        "target": round(float(ltp) * 1.07, 2),
        "status": "PAPER TRADE ACTIVE",
    }
