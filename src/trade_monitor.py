from datetime import datetime


def monitor_trade(trade, current_price):

    entry = float(trade["entry"])
    current_price = float(current_price)

    quantity = trade["remaining_quantity"]

    initial_stop = float(
        trade.get(
            "initial_stop_loss",
            trade["stop_loss"]
        )
    )

    stop_loss = float(trade["stop_loss"])

    target1 = float(trade["target1"])
    target2 = float(trade["target2"])

    target1_hit = False

    # ---------------------------------------------------------
    # TARGET 1 — PARTIAL BOOKING
    # ---------------------------------------------------------
    if (
        not trade["partial_booked"]
        and current_price >= target1
    ):

        trade["partial_booked"] = True

        booked_qty = quantity // 2

        realized = round(
            (target1 - entry) * booked_qty,
            2
        )

        trade["realized_pnl"] = round(
            trade.get("realized_pnl", 0) + realized,
            2
        )

        trade["remaining_quantity"] = (
            quantity - booked_qty
        )

        quantity = trade["remaining_quantity"]

        # Move remaining position stop to breakeven.
        stop_loss = entry
        trade["stop_loss"] = stop_loss

        target1_hit = True

        print(">>> TARGET 1 HIT - 50% BOOKED")
        print(f">>> Booked Qty: {booked_qty}")
        print(f">>> Remaining Qty: {quantity}")
        print(f">>> Realized P/L: {trade['realized_pnl']}")
        print(f">>> SL moved to Entry: {entry}")

    # ---------------------------------------------------------
    # TRAILING STOP
    # ---------------------------------------------------------
    #
    # IMPORTANT:
    # If Target 1 was just hit on this tick, do not immediately
    # apply the trailing calculation again.
    #
    # The next market-price update can trail the remaining
    # position normally.
    #
    risk = entry - initial_stop

    if risk > 0 and not target1_hit:

        if current_price >= entry + risk:
            stop_loss = max(
                stop_loss,
                entry
            )

        if current_price >= entry + (2 * risk):
            stop_loss = max(
                stop_loss,
                current_price - risk
            )

    trade["stop_loss"] = round(
        stop_loss,
        2
    )

    # ---------------------------------------------------------
    # P/L
    # ---------------------------------------------------------

    unrealized = round(
        (current_price - entry) * quantity,
        2
    )

    realized = round(
        trade.get("realized_pnl", 0),
        2
    )

    pnl = round(
        realized + unrealized,
        2
    )

    pnl_percent = round(
        ((current_price - entry) / entry) * 100,
        2
    )

    status = "RUNNING"
    exit_reason = ""

    # ---------------------------------------------------------
    # TARGET 2
    # ---------------------------------------------------------

    if current_price >= target2:

        status = "TARGET 2 HIT"
        exit_reason = "TARGET2"

    # ---------------------------------------------------------
    # STOP LOSS
    # ---------------------------------------------------------

    elif current_price <= stop_loss:

        status = "STOP LOSS HIT"
        exit_reason = "TRAILING_STOP"

    return {

        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "contract": trade["contract"],

        "entry": entry,

        "current": current_price,

        "quantity": quantity,

        "stop_loss": stop_loss,

        "target": target2,

        "pnl": pnl,

        "pnl_percent": pnl_percent,

        "status": status,

        "exit_reason": exit_reason,

        "target1_hit": target1_hit,

        "closed": status != "RUNNING",
    }
