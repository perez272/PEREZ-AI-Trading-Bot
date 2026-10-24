from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.active_position_guard import release_contract
from src.paper_trade_lifecycle import now_utc

IST = ZoneInfo("Asia/Kolkata")
EXPIRY_TRAIL_ACTIVATION_INR = 15.0
EXPIRY_TRAIL_BUFFER_INR = 15.0


def _expiry_date(trade):
    """Parse common broker expiry formats; fail closed to normal exits if unknown."""
    raw = str(trade.get("expiry") or trade.get("expiry_date") or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%y", "%d %b %y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _is_expiry_day(trade, timestamp):
    """True only when a parseable contract expiry matches the India market date."""
    expiry = _expiry_date(trade)
    if expiry is None:
        return False
    try:
        instant = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=IST)
        return expiry == instant.astimezone(IST).date()
    except (TypeError, ValueError):
        return False


def monitor_trade(trade, current_price):
    """Evaluate one paper trade and retain MFE/MAE for outcome learning.

    Normal trades retain their existing target/stop behavior. On the contract's
    actual expiry date (India time), fixed targets are bypassed and a ₹15
    per-unit trailing exit activates only after price reaches entry + ₹15.
    """
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
    if trade.get("time_stop_breakeven"):
        initial_stop = max(initial_stop, entry)
    stop_loss = initial_stop
    target1 = float(trade["target1"])
    target2 = float(trade["target2"])
    expiry_day = _is_expiry_day(trade, now_utc())

    high_watermark = max(float(trade.get("high_watermark", entry)), current_price)
    low_watermark = min(float(trade.get("low_watermark", entry)), current_price)
    trade["high_watermark"] = round(high_watermark, 2)
    trade["low_watermark"] = round(low_watermark, 2)
    mfe = round(max(0.0, (high_watermark - entry) / max(abs(entry), 1e-9) * 100.0), 2)
    mae = round(min(0.0, (low_watermark - entry) / max(abs(entry), 1e-9) * 100.0), 2)
    trade["mfe"] = mfe
    trade["mae"] = mae

    # Expiry-day mode deliberately bypasses both fixed targets. This is
    # scoped to the actual expiry date; malformed/missing expiry keeps legacy
    # behavior rather than accidentally enabling expiry-only logic.
    if not expiry_day and not trade["partial_booked"] and current_price >= target1:
        booked_qty = remaining // 2
        if booked_qty > 0:
            trade["partial_booked"] = True
            trade["realized_pnl"] = round(float(trade["realized_pnl"]) + (target1 - entry) * booked_qty, 2)
            remaining -= booked_qty
            trade["remaining_quantity"] = remaining
            print(">>> TARGET 1 HIT - 50% BOOKED")
            print(f">>> Booked Qty: {booked_qty}")
            print(f">>> Remaining Qty: {remaining}")
            print(f">>> Realized P/L: {trade['realized_pnl']}")

    # Expiry day: retain the hard stop until +₹15/unit is reached, then trail
    # ₹15 below the high watermark. The stop can only ratchet upward.
    expiry_trailing_active = bool(trade.get("expiry_trailing_active", False))
    if expiry_day and (expiry_trailing_active or current_price >= entry + EXPIRY_TRAIL_ACTIVATION_INR):
        expiry_trailing_active = True
        trade["expiry_trailing_active"] = True
        trailing_stop = high_watermark - EXPIRY_TRAIL_BUFFER_INR
        stop_loss = max(initial_stop, float(trade.get("stop_loss", initial_stop)), trailing_stop)
        trailing_pct = 0.0
    else:
        # Legacy non-expiry trailing behavior remains unchanged.
        trailing_pct = max(0.0, float(trade.get("trailing_stop_pct", 0.0) or 0.0))
        trailing_stop = (
            high_watermark * (1.0 - trailing_pct / 100.0)
            if trailing_pct > 0
            else initial_stop
        )
        stop_loss = max(initial_stop, trailing_stop)
    trade["stop_loss"] = round(stop_loss, 2)
    unrealized = round((current_price - entry) * remaining, 2)
    realized = round(float(trade.get("realized_pnl", 0.0)), 2)
    pnl = round(realized + unrealized, 2)
    initial_exposure = max(entry * original_quantity, 1.0)
    pnl_percent = round((pnl / initial_exposure) * 100, 2)

    status = "RUNNING"
    exit_reason = ""
    exit_price = None

    if not expiry_day and current_price >= target2 and remaining > 0:
        status = "TARGET 2 HIT"
        exit_reason = "TARGET_2"
        exit_price = current_price
        trade["realized_pnl"] = round(realized + (current_price - entry) * remaining, 2)
        trade["remaining_quantity"] = 0
        remaining = 0
        realized = trade["realized_pnl"]
        unrealized = 0.0
        pnl = realized
        pnl_percent = round((pnl / initial_exposure) * 100, 2)
    elif current_price <= stop_loss:
        status = "STOP LOSS HIT"
        exit_reason = "TRAILING_STOP" if stop_loss > initial_stop else "STOP_LOSS"
        exit_price = stop_loss
        trade["realized_pnl"] = round(realized + (exit_price - entry) * remaining, 2)
        trade["remaining_quantity"] = 0
        remaining = 0
        realized = trade["realized_pnl"]
        unrealized = 0.0
        pnl = realized
        pnl_percent = round((pnl / initial_exposure) * 100, 2)

    result = {
        "time": now_utc(),
        "contract": trade["contract"], "entry": entry, "current": current_price,
        "exit_price": exit_price if status != "RUNNING" else None,
        "quantity": remaining, "original_quantity": original_quantity,
        "remaining_quantity": remaining, "stop_loss": stop_loss, "target": target2,
        "target1": target1, "target2": target2,
        "high_watermark": high_watermark, "low_watermark": low_watermark,
        "trailing_stop_pct": trailing_pct, "expiry_day": expiry_day,
        "expiry_trailing_active": expiry_trailing_active, "mfe": mfe, "mae": mae,
        "realized_pnl": realized, "unrealized_pnl": unrealized, "pnl": pnl,
        "pnl_percent": pnl_percent, "status": status, "exit_reason": exit_reason,
        "target1_hit": bool(trade.get("partial_booked")), "closed": status != "RUNNING",
    }
    if result["closed"]:
        release_contract(trade["contract"], trade.get("trade_id"))
    return result
