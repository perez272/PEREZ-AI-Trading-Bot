"""Micro-account controls for the strict Rs 5,000 paper-account paradigm."""

from __future__ import annotations

import logging
import math
from typing import Callable, Mapping

from src.dynamic_strike_selector import select_target_strike

LOGGER = logging.getLogger(__name__)

MICRO_ACCOUNT_CAPITAL = 5000.0
ENTRY_BUFFER_INR = 200.0
MAX_ENTRY_CAPITAL_INR = MICRO_ACCOUNT_CAPITAL - ENTRY_BUFFER_INR
MAX_RISK_PER_TRADE_INR = 750.0
MAX_DAILY_TRADES = 2
MAX_SPREAD_PCT = 1.0

INDEX_LOT_SIZES = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 50,
}


def _lot_size(symbol: str, contract: Mapping | None = None) -> int:
    """Use the contract lot size when supplied; otherwise use the micro-account map."""
    if contract:
        try:
            value = int(float(contract.get("lotsize", 0)))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    try:
        value = INDEX_LOT_SIZES[str(symbol).upper().strip()]
    except KeyError as exc:
        raise ValueError(f"Unsupported micro-account index: {symbol}") from exc
    return value


def build_strike_sequence(symbol: str, spot: float, option_type: str, itm_depth: int = 1) -> list[float]:
    """Return ITM target, ATM, then up to three OTM strikes."""
    option_type = str(option_type).upper().strip()
    if option_type not in {"CE", "PE"}:
        raise ValueError("option_type must be CE or PE")
    atm = select_target_strike(symbol, spot, option_type, itm_depth=0)
    step = abs(select_target_strike(symbol, spot, option_type, itm_depth=1) - atm)
    initial = select_target_strike(symbol, spot, option_type, itm_depth=itm_depth)
    if itm_depth == 0:
        initial = atm

    sequence = [float(initial)]
    if initial != atm:
        sequence.append(float(atm))

    # Three OTM candidates: this is the maximum permitted downgrade depth.
    for depth in range(1, 4):
        strike = atm + step * depth if option_type == "CE" else atm - step * depth
        sequence.append(float(strike))
    return sequence


def select_affordable_strike(
    symbol: str,
    spot: float,
    option_type: str,
    contracts_by_strike: Mapping[float, Mapping],
    ltp_getter: Callable[[Mapping], float],
    max_entry_capital: float = MAX_ENTRY_CAPITAL_INR,
    itm_depth: int = 1,
) -> dict | None:
    """Select the first live-priced strike requiring no more than Rs 4,800.

    The search starts at ATM/1-strike ITM and moves through ATM/OTM strikes,
    stopping after three OTM strikes.
    """
    try:
        max_capital = float(max_entry_capital)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_entry_capital must be positive") from exc
    if max_capital <= 0:
        raise ValueError("max_entry_capital must be positive")

    sequence = build_strike_sequence(symbol, spot, option_type, itm_depth=itm_depth)
    for strike in sequence:
        contract = contracts_by_strike.get(strike)
        if contract is None:
            contract = contracts_by_strike.get(float(strike))
        if contract is None:
            continue
        # Pass the actual candidate strike to live-price adapters/callbacks.
        priced_contract = {**dict(contract), "strike": float(strike)}
        lot_size = _lot_size(symbol, priced_contract)
        try:
            ltp = float(ltp_getter(priced_contract))
        except (TypeError, ValueError, Exception) as exc:
            LOGGER.warning(
                "INSUFFICIENT_CAPITAL_FOR_SETUP symbol=%s strike=%s reason=LTP_UNAVAILABLE error=%s",
                symbol, strike, exc,
            )
            continue
        if not math.isfinite(ltp) or ltp <= 0:
            continue

        required = round(ltp * lot_size, 2)
        if required <= max_capital:
            return {
                **priced_contract,
                "lotsize": lot_size,
                "ltp": ltp,
                "required_capital": required,
                "capital_limit": max_capital,
            }

    LOGGER.warning(
        "INSUFFICIENT_CAPITAL_FOR_SETUP symbol=%s option_type=%s max_entry_capital=%.2f",
        symbol, option_type, max_capital,
    )
    return None


def calculate_rupee_stop_loss(
    entry_premium: float,
    lot_size: int,
    max_risk_inr: float = MAX_RISK_PER_TRADE_INR,
) -> dict:
    """Calculate a hard premium stop from a fixed rupee risk budget."""
    entry = float(entry_premium)
    lot = int(lot_size)
    risk = float(max_risk_inr)
    if not math.isfinite(entry) or entry <= 0:
        raise ValueError("entry_premium must be positive")
    if lot <= 0:
        raise ValueError("lot_size must be positive")
    if not math.isfinite(risk) or risk <= 0:
        raise ValueError("max_risk_inr must be positive")

    max_points_loss = risk / lot
    stop_loss = round(entry - max_points_loss, 2)
    return {
        "entry": round(entry, 2),
        "lot_size": lot,
        "max_risk_inr": round(risk, 2),
        "max_points_loss": round(max_points_loss, 2),
        "stop_loss": stop_loss,
    }


def spread_is_safe(
    bid: float,
    ask: float,
    max_spread_pct: float = MAX_SPREAD_PCT,
    logger: logging.Logger | None = None,
) -> bool:
    """Return False when the best bid/ask spread is above 1%."""
    log = logger or LOGGER
    bid = float(bid)
    ask = float(ask)
    limit = float(max_spread_pct)
    if bid <= 0 or ask <= 0 or ask < bid:
        log.warning("SPREAD_TOO_WIDE bid=%.4f ask=%.4f reason=INVALID_ORDER_BOOK", bid, ask)
        return False
    spread_pct = (ask - bid) / bid * 100.0
    if spread_pct > limit:
        log.warning(
            "SPREAD_TOO_WIDE bid=%.4f ask=%.4f spread_pct=%.4f max_spread_pct=%.4f",
            bid, ask, spread_pct, limit,
        )
        return False
    return True


def daily_trade_limit_allows(
    trades_taken_today: int,
    max_daily_trades: int = MAX_DAILY_TRADES,
    logger: logging.Logger | None = None,
) -> bool:
    """Enforce the strict two-trade micro-account daily limit."""
    log = logger or LOGGER
    count = int(trades_taken_today)
    limit = int(max_daily_trades)
    if count >= limit:
        log.warning(
            "MAX_DAILY_TRADES_HIT trades_taken_today=%d max_daily_trades=%d",
            count, limit,
        )
        return False
    return True
