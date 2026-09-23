"""Hybrid exit state machine for one-lot option positions."""

import logging
from datetime import date, datetime
from typing import Dict, Union

LOGGER = logging.getLogger(__name__)

EXPIRY_WEEKDAYS = {
    "NIFTY": 1,    # Tuesday
    "SENSEX": 3,   # Thursday
}

TRAILING_ACTIVATION_POINTS = 15.0
TRAILING_BUFFER_POINTS = 15.0


def is_expiry_day(index_name: str, current_date: Union[datetime, date]) -> bool:
    """Return whether the supplied date is the mapped weekly expiry day."""
    if not index_name:
        return False
    normalized = str(index_name).strip().upper().replace("-", "").replace(" ", "")
    weekday = EXPIRY_WEEKDAYS.get(normalized)
    if weekday is None:
        return False
    value = current_date.date() if isinstance(current_date, datetime) else current_date
    if not isinstance(value, date):
        raise TypeError("current_date must be datetime or date")
    return value.weekday() == weekday


def evaluate_hybrid_exit(
    position_state: Dict,
    current_ltp: float,
    current_date: Union[datetime, date],
    index_name: str,
) -> str:
    """Evaluate the hybrid fixed-target/trailing-stop exit state machine.

    Mutates position_state with the expiry-day high watermark and ratcheted
    trailing stop. Returns HOLD, EXIT_TARGET, EXIT_STOP_LOSS, or EXIT_TRAIL.
    """
    current = float(current_ltp)
    entry = float(position_state["entry_price"])
    hard_sl = float(position_state["hard_sl_price"])
    target = float(position_state["target_1_price"])

    if is_expiry_day(index_name, current_date):
        LOGGER.info("Regime: Expiry Day -> Trailing Stop active")
        highest = max(float(position_state.get("highest_price_reached", entry)), current)
        previous_trail = float(position_state.get("trailing_sl_price", hard_sl))

        position_state["highest_price_reached"] = round(highest, 2)

        # The hard SL remains active until the option has gained 15 points.
        if highest < entry + TRAILING_ACTIVATION_POINTS:
            position_state["trailing_sl_price"] = round(max(previous_trail, hard_sl), 2)
            if current <= hard_sl:
                return "EXIT_STOP_LOSS"
            return "HOLD"

        candidate_trail = highest - TRAILING_BUFFER_POINTS
        trailing_sl = max(previous_trail, hard_sl, candidate_trail)
        position_state["trailing_sl_price"] = round(trailing_sl, 2)

        if trailing_sl > previous_trail:
            LOGGER.info(
                "Trailing stop ratcheted up: %.2f -> %.2f (high watermark %.2f)",
                previous_trail,
                trailing_sl,
                highest,
            )

        if current <= trailing_sl:
            return "EXIT_TRAIL"
        return "HOLD"

    LOGGER.info("Regime: Normal Day -> Fixed Target active")
    if current <= hard_sl:
        return "EXIT_STOP_LOSS"
    if current >= target:
        return "EXIT_TARGET"
    return "HOLD"
