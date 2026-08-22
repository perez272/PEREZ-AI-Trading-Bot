from src.affordable_options import find_affordable_contract
from src.live_option_price import get_option_ltp
from src.upgrade_config import OPTION_MAX_PREMIUM

STOP_LOSS_PCT = 0.02
TARGET1_PCT = 0.05
TARGET2_PCT = 0.10


def resolve_option_contract(symbol, spot, signal):
    """Resolve an affordable, live-priced NFO option without creating a trade."""
    if signal not in ("BUY CE", "BUY PE"):
        return {"status": "NO TRADE", "reason": "No valid CE/PE signal"}

    option_type = "CE" if signal == "BUY CE" else "PE"
    affordable = find_affordable_contract(symbol, spot, option_type, get_option_ltp, OPTION_MAX_PREMIUM)
    if affordable.get("status") in ("NO CONTRACT", "NO AFFORDABLE OPTION"):
        return affordable

    return {
        "status": "CONTRACT VALID",
        "option_type": option_type,
        "contract": affordable["symbol"],
        "exchange": affordable["exchange"],
        "token": affordable["token"],
        "expiry": affordable["expiry"],
        "strike": affordable["strike"],
        "lotsize": int(affordable["lotsize"]),
        "ltp": float(affordable["ltp"]),
        "affordability_score": affordable["affordability_score"],
        "max_premium": OPTION_MAX_PREMIUM,
    }


def create_trade(symbol, spot, signal, capital, resolved=None):
    """Create a PAPER trade from one validated option contract.

    If ``resolved`` is supplied, it is reused so the execution path cannot
    silently select a different contract after the gate has approved one.
    """
    if capital is None or float(capital) <= 0:
        return {"status": "NO CAPITAL", "reason": "No valid live available capital"}

    if resolved is None:
        resolved = resolve_option_contract(symbol, spot, signal)

    if resolved.get("status") != "CONTRACT VALID":
        return resolved

    lot_size = int(resolved["lotsize"])
    ltp = float(resolved["ltp"])
    if lot_size <= 0 or ltp <= 0:
        return {"status": "INVALID CONTRACT", "reason": "Contract has invalid lot size or LTP"}

    lots = int(float(capital) // (ltp * lot_size))
    if lots < 1:
        return {"status": "LOW CAPITAL", "reason": f"One lot needs Rs {ltp * lot_size:.2f}"}

    quantity = lots * lot_size
    investment = round(quantity * ltp, 2)
    entry = ltp
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
        "strike": resolved["strike"],
        "entry": entry,
        "quantity": quantity,
        "remaining_quantity": quantity,
        "lots": lots,
        "investment": investment,
        "capital_available": round(float(capital), 2),
        "capital_utilization_pct": round(investment / float(capital) * 100.0, 2),
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
