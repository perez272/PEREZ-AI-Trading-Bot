from src.affordable_options import find_affordable_contract
from src.live_option_price import get_option_ltp, get_option_ltp_batch
from src.upgrade_config import OPTION_MAX_PREMIUM

STOP_LOSS_PCT = 0.02
TARGET1_PCT = 0.05
TARGET2_PCT = 0.10
MAX_CAPITAL_UTILIZATION = 0.90


def resolve_option_contract(symbol, spot, signal):
    """Resolve an affordable, live-priced NFO option without creating a trade."""
    if signal not in ("BUY CE", "BUY PE"):
        return {"status": "NO TRADE", "reason": "No valid CE/PE signal"}

    option_type = "CE" if signal == "BUY CE" else "PE"
    affordable = find_affordable_contract(
        symbol,
        spot,
        option_type,
        get_option_ltp,
        OPTION_MAX_PREMIUM,
        batch_ltp_getter=get_option_ltp_batch,
    )
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


def create_trade(symbol, spot, signal, capital, resolved_contract=None):
    """Create a PAPER trade from one validated option contract.

    If ``resolved_contract`` is supplied, it is reused exactly so the option
    that passed the options gate cannot silently change before trade creation.
    """
    if capital is None or float(capital) <= 0:
        return {"status": "NO CAPITAL", "reason": "No valid live available capital"}

    if resolved_contract is None:
        resolved = resolve_option_contract(symbol, spot, signal)
    else:
        resolved = dict(resolved_contract)

    if resolved.get("status") != "CONTRACT VALID":
        return resolved

    expected_option_type = "CE" if signal == "BUY CE" else "PE" if signal == "BUY PE" else None
    if expected_option_type is None or resolved.get("option_type") != expected_option_type:
        return {"status": "INVALID CONTRACT", "reason": "Validated contract does not match trade signal"}

    required = ("contract", "exchange", "token", "expiry", "strike", "lotsize", "ltp")
    missing = [key for key in required if resolved.get(key) in (None, "")]
    if missing:
        return {"status": "INVALID CONTRACT", "reason": f"Missing validated contract fields: {', '.join(missing)}"}

    lot_size = int(resolved["lotsize"])
    ltp = float(resolved["ltp"])
    if lot_size < 1 or ltp <= 0:
        return {"status": "INVALID CONTRACT", "reason": "Invalid lot size or LTP"}
    if ltp > OPTION_MAX_PREMIUM:
        return {"status": "PRICE_CHANGED", "reason": f"Option premium Rs {ltp:.2f} exceeds cap Rs {OPTION_MAX_PREMIUM:.2f}"}

    deployable_capital = float(capital) * MAX_CAPITAL_UTILIZATION
    lots = int(deployable_capital // (ltp * lot_size))
    if lots < 1:
        return {"status": "LOW CAPITAL", "reason": f"One lot needs Rs {ltp * lot_size:.2f}"}

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
        "strike": resolved["strike"],
        "entry": entry,
        "quantity": quantity,
        "original_quantity": quantity,
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
