from src.contract_selector import select_contract
from src.live_option_price import get_option_ltp


STOP_LOSS_PCT = 0.02
TARGET1_PCT = 0.05
TARGET2_PCT = 0.10


def resolve_option_contract(symbol, spot, signal):
    """Resolve and validate the option contract/LTP without creating a trade."""
    if signal not in ("BUY CE", "BUY PE"):
        return {"status": "NO TRADE", "reason": "No valid CE/PE signal"}

    option_type = "CE" if signal == "BUY CE" else "PE"
    contract = select_contract(symbol, spot, option_type)

    if not contract or contract.get("status") == "NO CONTRACT":
        return {"status": "NO CONTRACT", "reason": contract.get("reason", "No contract") if contract else "No contract"}

    try:
        ltp = get_option_ltp(
            contract["exchange"],
            contract["symbol"],
            contract["token"],
        )
    except Exception as exc:
        return {"status": "NO LTP", "reason": repr(exc)}

    if not ltp or ltp <= 0:
        return {"status": "NO LTP", "reason": "Invalid option LTP"}

    return {
        "status": "CONTRACT VALID",
        "option_type": option_type,
        "contract": contract["symbol"],
        "exchange": contract["exchange"],
        "token": contract["token"],
        "expiry": contract["expiry"],
        "strike": contract.get("strike"),
        "lotsize": int(float(contract["lotsize"])),
        "ltp": float(ltp),
    }


def create_trade(symbol, spot, signal, capital=5000):
    """Create a PAPER trade only after contract/LTP validation."""
    resolved = resolve_option_contract(symbol, spot, signal)

    if resolved.get("status") != "CONTRACT VALID":
        return resolved

    lot_size = resolved["lotsize"]
    ltp = resolved["ltp"]
    lots = int(capital // (ltp * lot_size))

    if lots < 1:
        return {
            "status": "LOW CAPITAL",
            "reason": f"One lot needs Rs {ltp * lot_size:.2f}",
        }

    quantity = lots * lot_size
    investment = round(quantity * ltp, 2)
    entry = float(ltp)
    stop_loss = round(entry * (1 - STOP_LOSS_PCT), 2)
    target1 = round(entry * (1 + TARGET1_PCT), 2)
    target2 = round(entry * (1 + TARGET2_PCT), 2)

    return {
        "symbol": symbol,
        "signal": signal,
        "contract": resolved["contract"],
        "exchange": resolved["exchange"],
        "token": resolved["token"],
        "expiry": resolved["expiry"],
        "entry": entry,
        "quantity": quantity,
        "remaining_quantity": quantity,
        "lots": lots,
        "investment": investment,
        "initial_stop_loss": stop_loss,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "target": target2,
        "partial_booked": False,
        "realized_pnl": 0.0,
        "status": "PAPER TRADE ACTIVE",
        "live_orders": False,
    }
