"""Black–Scholes analytics for NSE index-option chains.

This module is an analytics-only shadow component. It never places orders,
changes trade eligibility, or substitutes calculated values for broker data.

Conventions:
- volatility and IV are decimals (0.20 == 20% annualized)
- delta is per underlying point
- gamma is delta change per underlying point
- vega is option-price change per 1 volatility percentage point
- theta is option-price change per calendar day
- expiry date-only values mean 15:30 Asia/Kolkata on expiry day
- option prices are inferred from a valid bid/ask midpoint, never LTP fallback

The model is European Black–Scholes–Merton with continuously compounded
risk-free rate and dividend yield. It is a model estimate, not an executable
price or a guarantee of exchange/broker Greek conventions.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

LOG = logging.getLogger("PEREZ.GREEKS")
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

MIN_VOL = 1e-6
MAX_VOL = 5.0
IV_ITERATIONS = 80
PRICE_TOLERANCE = 1e-7


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _as_expiry_datetime(value: Any) -> datetime:
    """Parse an expiry timestamp; date-only input means 15:30 IST."""
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, time(15, 30))
    else:
        raw = str(value).strip()
        if not raw:
            raise ValueError("EXPIRY_MISSING")
        try:
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            result = datetime.combine(
                datetime.strptime(raw[:10], "%Y-%m-%d").date(),
                time(15, 30),
            )

    if result.tzinfo is None:
        result = result.replace(tzinfo=IST)
    return result.astimezone(UTC)


def time_to_expiry_years(expiry: Any, now: datetime | None = None) -> float:
    """Actual seconds to expiry divided by 365 days."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    seconds = (_as_expiry_datetime(expiry) - current.astimezone(UTC)).total_seconds()
    return max(0.0, seconds / (365.0 * 24.0 * 60.0 * 60.0))


def _validate_inputs(
    spot: float,
    strike: float,
    years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
    option_type: str,
) -> str:
    kind = str(option_type).upper()
    values = (spot, strike, years, rate, dividend_yield, volatility)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("NON_FINITE_MODEL_INPUT")
    if spot <= 0 or strike <= 0 or years <= 0 or volatility <= 0:
        raise ValueError("SPOT_STRIKE_TTE_AND_VOLATILITY_MUST_BE_POSITIVE")
    if not -0.25 <= rate <= 1.0:
        raise ValueError("RISK_FREE_RATE_OUT_OF_SUPPORTED_RANGE")
    if not -0.25 <= dividend_yield <= 1.0:
        raise ValueError("DIVIDEND_YIELD_OUT_OF_SUPPORTED_RANGE")
    if kind not in {"CE", "PE"}:
        raise ValueError("OPTION_TYPE_MUST_BE_CE_OR_PE")
    return kind


def black_scholes_greeks(
    spot: float,
    strike: float,
    years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
    option_type: str,
) -> dict[str, float]:
    """Return BSM theoretical value and Greeks for a European option."""
    s, k, t, r, q, sigma = map(
        float, (spot, strike, years, rate, dividend_yield, volatility)
    )
    kind = _validate_inputs(s, k, t, r, q, sigma, option_type)

    sqrt_t = math.sqrt(t)
    d1 = (
        math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t
    ) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    pdf = _normal_pdf(d1)

    gamma = disc_q * pdf / (s * sigma * sqrt_t)
    vega = s * disc_q * pdf * sqrt_t / 100.0

    if kind == "CE":
        price = s * disc_q * _normal_cdf(d1) - k * disc_r * _normal_cdf(d2)
        delta = disc_q * _normal_cdf(d1)
        theta_annual = (
            -s * disc_q * pdf * sigma / (2.0 * sqrt_t)
            - r * k * disc_r * _normal_cdf(d2)
            + q * s * disc_q * _normal_cdf(d1)
        )
    else:
        price = k * disc_r * _normal_cdf(-d2) - s * disc_q * _normal_cdf(-d1)
        delta = disc_q * (_normal_cdf(d1) - 1.0)
        theta_annual = (
            -s * disc_q * pdf * sigma / (2.0 * sqrt_t)
            + r * k * disc_r * _normal_cdf(-d2)
            - q * s * disc_q * _normal_cdf(-d1)
        )

    return {
        "price": max(0.0, price),
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta_per_day": theta_annual / 365.0,
        "d1": d1,
        "d2": d2,
    }


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    dividend_yield: float,
    option_type: str,
    *,
    max_iterations: int = IV_ITERATIONS,
    price_tolerance: float = PRICE_TOLERANCE,
) -> float:
    """Solve annualized IV by bounded bisection; NaN means unsolvable."""
    try:
        price, s, k, t, r, q = map(
            float, (market_price, spot, strike, years, rate, dividend_yield)
        )
        kind = str(option_type).upper()
        if not all(math.isfinite(x) for x in (price, s, k, t, r, q)):
            return math.nan
        if price <= 0 or s <= 0 or k <= 0 or t <= 0 or kind not in {"CE", "PE"}:
            return math.nan

        disc_r = math.exp(-r * t)
        disc_q = math.exp(-q * t)
        if kind == "CE":
            lower = max(0.0, s * disc_q - k * disc_r)
            upper = s * disc_q
        else:
            lower = max(0.0, k * disc_r - s * disc_q)
            upper = k * disc_r

        if price < lower - price_tolerance or price >= upper:
            return math.nan

        lo, hi = MIN_VOL, MAX_VOL
        high_value = black_scholes_greeks(
            s, k, t, r, q, hi, kind
        )["price"]
        if price > high_value + price_tolerance:
            return math.nan

        for _ in range(max_iterations):
            mid = (lo + hi) / 2.0
            model_price = black_scholes_greeks(
                s, k, t, r, q, mid, kind
            )["price"]
            if abs(model_price - price) <= price_tolerance:
                return mid
            if model_price < price:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        LOG.debug("IV solver could not solve supplied market observation", exc_info=True)
        return math.nan


def calculate_chain_greeks(
    chain: pd.DataFrame,
    *,
    risk_free_rate: float,
    dividend_yield: float,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Calculate IV/Greeks row-by-row without mutating the caller's DataFrame.

    Required columns: spot, strike, expiry, option_type, bid, ask.
    A valid bid/ask midpoint is mandatory. LTP fallback is deliberately
    prohibited because it may be stale or outside the executable market.
    """
    required = {"spot", "strike", "expiry", "option_type", "bid", "ask"}
    missing = required.difference(chain.columns)
    if missing:
        raise ValueError(f"MISSING_OPTION_CHAIN_COLUMNS:{','.join(sorted(missing))}")
    if not math.isfinite(float(risk_free_rate)) or not -0.25 <= risk_free_rate <= 1.0:
        raise ValueError("INVALID_RISK_FREE_RATE")
    if not math.isfinite(float(dividend_yield)) or not -0.25 <= dividend_yield <= 1.0:
        raise ValueError("INVALID_DIVIDEND_YIELD")

    current = now or datetime.now(IST)
    output = chain.copy()
    calculated = [
        "bs_market_mid", "bs_price", "bs_iv", "bs_delta", "bs_gamma",
        "bs_vega", "bs_theta_per_day", "bs_status", "bs_error",
    ]
    for column in calculated:
        output[column] = math.nan if column not in {"bs_status", "bs_error"} else ""

    for idx, row in output.iterrows():
        try:
            s, k, bid, ask = map(
                float, (row["spot"], row["strike"], row["bid"], row["ask"])
            )
            kind = str(row["option_type"]).strip().upper()
            if not all(math.isfinite(x) for x in (s, k, bid, ask)):
                raise ValueError("NON_FINITE_QUOTE")
            if s <= 0 or k <= 0 or bid <= 0 or ask < bid:
                raise ValueError("INVALID_BID_ASK_OR_SPOT")
            years = time_to_expiry_years(row["expiry"], current)
            if years <= 0:
                raise ValueError("EXPIRED_OR_ZERO_TTE")

            midpoint = (bid + ask) / 2.0
            iv = implied_volatility(
                midpoint, s, k, years, float(risk_free_rate),
                float(dividend_yield), kind,
            )
            if not math.isfinite(iv):
                raise ValueError("IV_UNSOLVABLE_FROM_BID_ASK_MID")

            greeks = black_scholes_greeks(
                s, k, years, float(risk_free_rate),
                float(dividend_yield), iv, kind,
            )
            output.at[idx, "bs_market_mid"] = midpoint
            output.at[idx, "bs_price"] = greeks["price"]
            output.at[idx, "bs_iv"] = iv
            output.at[idx, "bs_delta"] = greeks["delta"]
            output.at[idx, "bs_gamma"] = greeks["gamma"]
            output.at[idx, "bs_vega"] = greeks["vega"]
            output.at[idx, "bs_theta_per_day"] = greeks["theta_per_day"]
            output.at[idx, "bs_status"] = "OK"
        except Exception as exc:
            output.at[idx, "bs_status"] = "SKIPPED"
            output.at[idx, "bs_error"] = str(exc)
            LOG.warning("Greek row skipped | index=%r | reason=%s", idx, exc)

    return output


def compare_broker_greeks(
    calculated: pd.DataFrame,
    *,
    broker_iv_column: str = "iv",
    broker_delta_column: str = "delta",
    broker_gamma_column: str = "gamma",
    broker_theta_column: str = "theta",
    broker_iv_is_percent: bool,
) -> pd.DataFrame:
    """Add broker-vs-model differences for shadow monitoring only.

    broker_iv_is_percent must be explicitly supplied because broker APIs
    differ in whether IV is represented as 18.5 or 0.185.
    Delta/Gamma/Theta are assumed to already use matching units.
    """
    output = calculated.copy()
    mapping = {
        "delta": (broker_delta_column, "bs_delta"),
        "gamma": (broker_gamma_column, "bs_gamma"),
        "theta_per_day": (broker_theta_column, "bs_theta_per_day"),
    }
    for name, (broker_col, model_col) in mapping.items():
        if broker_col in output.columns:
            broker = pd.to_numeric(output[broker_col], errors="coerce")
            model = pd.to_numeric(output[model_col], errors="coerce")
            output[f"{name}_broker_minus_model"] = broker - model

    if broker_iv_column in output.columns:
        broker_iv = pd.to_numeric(output[broker_iv_column], errors="coerce")
        if broker_iv_is_percent:
            broker_iv = broker_iv / 100.0
        model_iv = pd.to_numeric(output["bs_iv"], errors="coerce")
        output["iv_broker_minus_model"] = broker_iv - model_iv
    return output
