"""Observation-only Sniper Expiry Mode evaluation and historical path simulation.

This module never authorizes trades or submits orders. Missing confluence inputs
fail closed and remain explicitly visible in the simulation output.
"""
from __future__ import annotations

from datetime import datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ALLOWED_SYMBOLS = {"NIFTY", "SENSEX"}
ALLOWED_DTE = {"0DTE", "1DTE"}
MAX_ENTRY_INR = 4200.0
FLAT_BROKERAGE_INR = 30.0
PIN_START = time(11, 30)
PIN_END = time(13, 15)
LATE_0DTE = time(14, 15)


def _num(value):
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _local_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def evaluate_sniper_signal(observation: dict, context: dict | None = None) -> dict:
    """Evaluate strict confluence; absent context is a rejection, never a pass."""
    observation = observation if isinstance(observation, dict) else {}
    context = context if isinstance(context, dict) else {}
    reasons = []
    checks = {}
    symbol = str(observation.get("symbol") or "").upper()
    bucket = str(observation.get("expiry_bucket") or "").upper()
    checks["universe"] = symbol in ALLOWED_SYMBOLS
    checks["expiry"] = bucket in ALLOWED_DTE
    if not checks["universe"]:
        reasons.append("UNSUPPORTED_SYMBOL")
    if not checks["expiry"]:
        reasons.append("NOT_0DTE_OR_1DTE")

    observed = _local_time(observation.get("observed_at"))
    if observed is None:
        observed = _local_time(context.get("observed_at"))
    local_clock = observed.timetz().replace(tzinfo=None) if observed else None
    midday = bool(local_clock and PIN_START <= local_clock <= PIN_END)
    late = bool(bucket == "0DTE" and local_clock and local_clock >= LATE_0DTE)
    checks["outside_midday_chop"] = not midday
    checks["before_0dte_cutoff"] = not late
    if midday:
        reasons.append("MIDDAY_CHOP_WINDOW")
    if late:
        reasons.append("0DTE_ENTRY_CUTOFF")

    spot = _num(observation.get("spot"))
    max_pain = _num(observation.get("max_pain_strike"))
    step = _num(observation.get("strike_step"))
    pin_distance = abs(spot - max_pain) if spot is not None and max_pain is not None else None
    near_max_pain = bool(pin_distance is not None and step and pin_distance <= step * 0.5)
    checks["not_max_pain_pinned"] = not bool(observation.get("pinning_candidate")) and not near_max_pain
    if not checks["not_max_pain_pinned"]:
        reasons.append("MAX_PAIN_PINNING")

    direction = str(context.get("breakout_direction") or "").upper()
    if direction not in {"CE", "PE"}:
        direction = ""
    breakout_level = _num(context.get("breakout_level"))
    crossed = bool(spot is not None and breakout_level is not None and
                   ((direction == "CE" and spot > breakout_level) or
                    (direction == "PE" and spot < breakout_level)))
    structure = bool(context.get("orb_breakout") or context.get("session_extreme_breakout"))
    mtf = context.get("mtf_moves_pct") if isinstance(context.get("mtf_moves_pct"), dict) else {}
    m1, m3, m5 = (_num(mtf.get(key)) for key in ("1m", "3m", "5m"))
    if direction == "CE":
        momentum = bool(m1 is not None and m3 is not None and m5 is not None
                        and m1 >= 0.05 and m3 >= 0.10 and m5 >= 0.15)
    elif direction == "PE":
        momentum = bool(m1 is not None and m3 is not None and m5 is not None
                        and m1 <= -0.05 and m3 <= -0.10 and m5 <= -0.15)
    else:
        momentum = False
    checks["underlying_structure_breakout"] = structure and crossed
    checks["multi_timeframe_momentum"] = momentum
    if not checks["underlying_structure_breakout"]:
        reasons.append("ORB_OR_SESSION_BREAKOUT_UNCONFIRMED")
    if not momentum:
        reasons.append("MULTI_TIMEFRAME_MOMENTUM_UNCONFIRMED")

    evidence = observation.get("oi_evidence") or []
    near = []
    if spot is not None and step:
        near = [row for row in evidence if isinstance(row, dict)
                and _num(row.get("strike")) is not None
                and abs(_num(row.get("strike")) - spot) <= step * 1.5]
    writer_side = "CE" if direction == "CE" else "PE" if direction == "PE" else ""
    unwind = any(row.get("side") == writer_side
                 and _num(row.get("oi_change")) is not None and _num(row.get("oi_change")) < 0
                 and _num(row.get("premium_change")) is not None and _num(row.get("premium_change")) > 0
                 for row in near)
    volume_ratio = _num(context.get("option_volume_ratio"))
    checks["writer_short_covering"] = unwind
    checks["rapid_option_volume_expansion"] = volume_ratio is not None and volume_ratio >= 2.0
    if not unwind:
        reasons.append("ATM_NEAR_ITM_WRITER_UNWIND_MISSING")
    if not checks["rapid_option_volume_expansion"]:
        reasons.append("OPTION_VOLUME_SPIKE_MISSING")

    passed = all(checks.values())
    return {
        "symbol": symbol or None, "expiry_bucket": bucket or None,
        "direction": direction or None, "observed_at": observation.get("observed_at"),
        "eligible": passed, "status": "SNIPER_CONFLUENCE_CONFIRMED" if passed else "REJECTED",
        "checks": checks, "rejection_reasons": reasons,
        "safety": "OBSERVATION_ONLY",
        "note": "Missing ORB, multi-timeframe, volume, or option-chain evidence fails closed; this result never authorizes an order.",
    }


def select_sniper_contract(candidates: list[dict], spot: float, strike_step: float,
                           side: str, capital: float = MAX_ENTRY_INR) -> dict:
    """Rank only ATM/one-strike neighbours with real delta, gamma and whole-lot cost."""
    spot, strike_step, capital = _num(spot), _num(strike_step), _num(capital)
    side = str(side or "").upper()
    if spot is None or strike_step is None or strike_step <= 0 or side not in {"CE", "PE"}:
        return {"selected": None, "reason": "INVALID_SELECTION_CONTEXT", "candidates": []}
    ranked = []
    for row in candidates or []:
        if not isinstance(row, dict) or str(row.get("side") or "").upper() != side:
            continue
        strike, premium = _num(row.get("strike")), _num(row.get("ltp"))
        delta, gamma = _num(row.get("delta")), _num(row.get("gamma"))
        lot = _num(row.get("lot_size"))
        if None in (strike, premium, delta, gamma, lot) or premium <= 0 or gamma <= 0 or lot < 1:
            continue
        if abs(strike - spot) > strike_step * 1.51 or not 0.45 <= abs(delta) <= 0.60:
            continue
        quantity = int(lot)
        cost = premium * quantity
        if cost > capital:
            continue
        ranked.append({**row, "estimated_entry_cost": round(cost, 2),
                       "whole_lot_quantity": quantity, "gamma_rank": gamma})
    ranked.sort(key=lambda row: (row["gamma_rank"], _num(row.get("volume_ratio")) or 0), reverse=True)
    return {"selected": ranked[0] if ranked else None,
            "reason": "HIGHEST_GAMMA_AFFORDABLE_NEAR_ATM" if ranked else "NO_VALID_GAMMA_DELTA_AFFORDABLE_CONTRACT",
            "candidates": ranked, "safety": "OBSERVATION_ONLY"}


def simulate_runner(path: list[dict], entry: float, initial_stop: float,
                    quantity: int, brokerage: float = FLAT_BROKERAGE_INR,
                    activation_pct: float = 45.0, atr_multiple: float = 1.5) -> dict:
    """Simulate an all-quantity EMA/ATR runner on recorded premium observations only."""
    entry, initial_stop = _num(entry), _num(initial_stop)
    brokerage = _num(brokerage)
    if entry is None or initial_stop is None or entry <= 0 or quantity < 1 or brokerage is None:
        return {"status": "INSUFFICIENT_INPUT", "exit_price": None, "net_pnl": None}
    prices = [_num(point.get("price")) for point in path or [] if isinstance(point, dict)]
    prices = [price for price in prices if price is not None and price > 0]
    if not prices:
        return {"status": "NO_RECORDED_PATH", "exit_price": None, "net_pnl": None}
    ema = None
    alpha = 2.0 / 4.0
    previous = None
    ranges = []
    high = entry
    active = False
    stop = initial_stop
    exit_price = None
    exit_index = None
    for index, price in enumerate(prices):
        high = max(high, price)
        ema = price if ema is None else alpha * price + (1 - alpha) * ema
        if previous is not None:
            ranges.append(abs(price - previous))
        atr = sum(ranges[-3:]) / min(3, len(ranges)) if ranges else 0.0
        if high >= entry * (1 + activation_pct / 100.0):
            active = True
        if active:
            breakeven = entry + brokerage / quantity
            trail = ema - atr_multiple * atr
            stop = max(stop, breakeven, trail)
        if price <= stop:
            exit_price, exit_index = stop, index
            break
        previous = price
    if exit_price is None:
        exit_price = prices[-1]
        exit_index = len(prices) - 1
    gross = (exit_price - entry) * quantity
    net = gross - brokerage
    return {
        "status": "TRAIL_EXIT" if exit_index < len(prices) - 1 else "PATH_END",
        "activation_pct": activation_pct, "brokerage_inr": brokerage,
        "quantity": quantity, "exit_price": round(exit_price, 2),
        "gross_pnl": round(gross, 2), "net_pnl": round(net, 2),
        "net_return_pct": round(net / (entry * quantity) * 100, 2),
        "runner_activated": active, "final_stop": round(stop, 2),
        "observations_used": exit_index + 1, "safety": "SIMULATION_ONLY",
    }


def build_sniper_observations(observations: list[dict]) -> list[dict]:
    """Evaluate latest persisted OI snapshots; absent market context stays rejected."""
    result = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        evaluation = evaluate_sniper_signal(item, item.get("sniper_context"))
        result.append({**evaluation, "spot": item.get("spot"),
                       "max_pain_strike": item.get("max_pain_strike"),
                       "oi_direction": item.get("oi_direction"),
                       "breakout_status": item.get("breakout_status")})
    return result
