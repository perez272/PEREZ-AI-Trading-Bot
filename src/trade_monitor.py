from datetime import datetime

from src.active_position_guard import release_contract
from src.hybrid_exit_engine import evaluate_hybrid_exit, is_expiry_day
from src.paper_trade_lifecycle import now_utc


def monitor_trade(trade, current_price, current_date=None):
    """Evaluate one paper trade and retain MFE/MAE for outcome learning.

    The initial stop-loss is fixed for the full trade lifecycle. Targets may
    book profit, but the stop is never moved to breakeven or trailed.
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

    hybrid_exit_action = None
    index_name = str(trade.get("index_name") or trade.get("symbol") or "").strip().upper()
    hybrid_enabled = bool(trade.get("hybrid_exit_enabled") or index_name in {"NIFTY", "SENSEX"})
    if hybrid_enabled:
        if current_date is None:
            from datetime import timezone
            from zoneinfo import ZoneInfo
            current_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()
        position_state = {
            "entry_price": entry,
            "hard_sl_price": float(trade.get("hard_sl_price", initial_stop)),
            "target_1_price": float(trade.get("target_1_price", target1)),
            "highest_price_reached": float(trade.get("highest_price_reached", entry)),
            "trailing_sl_price": float(trade.get("trailing_sl_price", initial_stop)),
        }
        hybrid_exit_action = evaluate_hybrid_exit(
            position_state, current_price, current_date, index_name
        )
        trade["highest_price_reached"] = position_state["highest_price_reached"]
        trade["trailing_sl_price"] = position_state["trailing_sl_price"]
        trade["hybrid_exit_regime"] = (
            "EXPIRY" if is_expiry_day(index_name, current_date) else "NORMAL"
        )
        if trade["hybrid_exit_regime"] == "EXPIRY":
            stop_loss = float(trade["trailing_sl_price"])

    high_watermark = max(float(trade.get("high_watermark", entry)), current_price)
    low_watermark = min(float(trade.get("low_watermark", entry)), current_price)
    trade["high_watermark"] = round(high_watermark, 2)
    trade["low_watermark"] = round(low_watermark, 2)
    mfe = round(max(0.0, (high_watermark - entry) / max(abs(entry), 1e-9) * 100.0), 2)
    mae = round(min(0.0, (low_watermark - entry) / max(abs(entry), 1e-9) * 100.0), 2)
    trade["mfe"] = mfe
    trade["mae"] = mae

    if hybrid_exit_action is None and not trade["partial_booked"] and current_price >= target1:
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

    # High-watermark trailing stop: preserve the initial stop as the floor.
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

    if hybrid_exit_action in {"EXIT_TARGET", "EXIT_STOP_LOSS", "EXIT_TRAIL"}:
        status = {
            "EXIT_TARGET": "TARGET 1 HIT",
            "EXIT_STOP_LOSS": "STOP LOSS HIT",
            "EXIT_TRAIL": "TRAILING STOP HIT",
        }[hybrid_exit_action]
        exit_reason = {
            "EXIT_TARGET": "TARGET_1",
            "EXIT_STOP_LOSS": "STOP_LOSS",
            "EXIT_TRAIL": "TRAILING_STOP",
        }[hybrid_exit_action]
        exit_price = (
            current_price
            if hybrid_exit_action == "EXIT_TARGET"
            else hard_sl if hybrid_exit_action == "EXIT_STOP_LOSS"
            else float(trade["trailing_sl_price"])
        )
        trade["realized_pnl"] = round(
            float(trade.get("realized_pnl", 0.0)) + (exit_price - entry) * remaining, 2
        )
        trade["remaining_quantity"] = 0
        remaining = 0
        realized = trade["realized_pnl"]
        unrealized = 0.0
        pnl = realized
        initial_exposure = max(entry * original_quantity, 1.0)
        pnl_percent = round(pnl / initial_exposure * 100.0, 2)

    if hybrid_exit_action is None and current_price >= target2 and remaining > 0:
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
    elif hybrid_exit_action is None and current_price <= stop_loss:
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
        "trailing_stop_pct": trailing_pct, "mfe": mfe, "mae": mae,
        "hybrid_exit_action": hybrid_exit_action, "hybrid_exit_regime": trade.get("hybrid_exit_regime", ""),
        "highest_price_reached": trade.get("highest_price_reached", high_watermark),
        "trailing_sl_price": trade.get("trailing_sl_price", stop_loss),
        "realized_pnl": realized, "unrealized_pnl": unrealized, "pnl": pnl,
        "pnl_percent": pnl_percent, "status": status, "exit_reason": exit_reason,
        "target1_hit": bool(trade.get("partial_booked")), "closed": status != "RUNNING",
    }
    if result["closed"]:
        release_contract(trade["contract"], trade.get("trade_id"))
    return result
