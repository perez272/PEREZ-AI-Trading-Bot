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
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
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
    checks["observation_time_available"] = local_clock is not None
    checks["outside_midday_chop"] = not midday
    if local_clock is None:
        reasons.append("OBSERVATION_TIME_MISSING")
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
    writer_side = "CE" if direction == "CE" else "PE" if direction == "PE" else ""
    if spot is not None and step and writer_side:
        near = [row for row in evidence if isinstance(row, dict)
                and _num(row.get("strike")) is not None
                and abs(_num(row.get("strike")) - spot) <= step * 1.5
                and ((writer_side == "CE" and _num(row.get("strike")) <= spot + step * 0.5)
                     or (writer_side == "PE" and _num(row.get("strike")) >= spot - step * 0.5))]
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
        lot_quantity = int(lot)
        one_lot_cost = premium * lot_quantity
        if one_lot_cost <= 0 or one_lot_cost > capital:
            continue
        affordable_lots = int(capital // one_lot_cost)
        quantity = lot_quantity * affordable_lots
        cost = premium * quantity
        if affordable_lots < 1 or quantity % lot_quantity != 0 or cost > capital:
            continue
        ranked.append({**row, "estimated_entry_cost": round(cost, 2),
                       "whole_lot_quantity": quantity, "lot_size": lot_quantity,
                       "affordable_lots": affordable_lots, "gamma_rank": gamma})
    ranked.sort(key=lambda row: (row["gamma_rank"], _num(row.get("volume_ratio")) or 0,
                                 -row["estimated_entry_cost"]), reverse=True)
    return {"selected": ranked[0] if ranked else None,
            "reason": "HIGHEST_GAMMA_AFFORDABLE_NEAR_ATM" if ranked else "NO_VALID_GAMMA_DELTA_AFFORDABLE_CONTRACT",
            "candidates": ranked, "safety": "OBSERVATION_ONLY"}


def simulate_runner(path: list[dict], entry: float, initial_stop: float,
                    quantity: int, brokerage: float = FLAT_BROKERAGE_INR,
                    activation_pct: float = 45.0, atr_multiple: float = 1.5) -> dict:
    """Replay a full-quantity runner conservatively on recorded premium observations.

    Each observation is treated as the only available executable price. A gap
    through a stop is filled at the observed price, never at the more favourable
    stop level. The trailing stop calculated from an observation becomes active
    only for the next observation (no same-tick look-ahead). This is a
    counterfactual full-quantity replay; it does not reproduce partial exits.
    """
    entry, initial_stop = _num(entry), _num(initial_stop)
    brokerage = _num(brokerage)
    activation_pct, atr_multiple = _num(activation_pct), _num(atr_multiple)
    valid_quantity = isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0
    if (entry is None or initial_stop is None or entry <= 0 or initial_stop <= 0
            or initial_stop >= entry or not valid_quantity or brokerage is None
            or brokerage < 0 or activation_pct is None or activation_pct < 0
            or atr_multiple is None or atr_multiple < 0):
        return {
            "status": "INSUFFICIENT_INPUT", "exit_price": None, "gross_pnl": None,
            "net_pnl": None, "runner_activated": False, "activation_status": "UNAVAILABLE",
            "activation_reason": "INSUFFICIENT_INPUT", "activation_threshold_price": None,
            "max_favorable_price": None, "execution_basis": "UNAVAILABLE",
        }

    prices = [_num(point.get("price")) for point in path or [] if isinstance(point, dict)]
    prices = [price for price in prices if price is not None and price > 0]
    if not prices:
        return {
            "status": "NO_RECORDED_PATH", "exit_price": None, "gross_pnl": None,
            "net_pnl": None, "runner_activated": False, "activation_status": "UNAVAILABLE",
            "activation_reason": "NO_RECORDED_PATH",
            "activation_threshold_price": round(entry * (1 + activation_pct / 100.0), 2),
            "max_favorable_price": None, "execution_basis": "UNAVAILABLE",
        }

    ema = None
    alpha = 2.0 / 4.0
    previous = None
    ranges = []
    high = entry
    active = False
    stop = initial_stop
    exit_price = None
    exit_index = None
    stop_trigger_price = None

    for index, price in enumerate(prices):
        # A stop established by earlier evidence is tested before this quote
        # can update the trail. If price gaps through it, use the observed price.
        if price <= stop:
            exit_price, exit_index, stop_trigger_price = price, index, stop
            break

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
        previous = price

    if exit_price is None:
        exit_price = prices[-1]
        exit_index = len(prices) - 1

    gross = (exit_price - entry) * quantity
    net = gross - brokerage
    return {
        "status": "TRAIL_EXIT" if stop_trigger_price is not None else "PATH_END",
        "activation_pct": activation_pct, "brokerage_inr": brokerage,
        "quantity": quantity, "exit_price": round(exit_price, 2),
        "gross_pnl": round(gross, 2), "net_pnl": round(net, 2),
        "net_return_pct": round(net / (entry * quantity) * 100, 2),
        "runner_activated": active,
        "activation_status": "ACTIVATED" if active else "NOT_REACHED",
        "activation_reason": "THRESHOLD_REACHED" if active else "MAX_FAVORABLE_MOVE_BELOW_THRESHOLD",
        "activation_threshold_price": round(entry * (1 + activation_pct / 100.0), 2),
        "max_favorable_price": round(high, 2),
        "max_favorable_pct": round((high / entry - 1) * 100.0, 2),
        "final_stop": round(stop, 2),
        "stop_trigger_price": round(stop_trigger_price, 2) if stop_trigger_price is not None else None,
        "execution_basis": "RECORDED_OBSERVATION_CONSERVATIVE_GAP_FILL",
        "position_model": "FULL_QUANTITY_COUNTERFACTUAL_NO_PARTIAL_EXITS",
        "observations_used": exit_index + 1, "safety": "SIMULATION_ONLY",
    }

def compare_runner_scenarios(
    path: list[dict], entry: float, initial_stop: float, quantity: int,
    brokerage: float = FLAT_BROKERAGE_INR,
    activation_pcts: tuple[float, ...] = (40.0, 45.0, 50.0),
    atr_multiples: tuple[float, ...] = (1.0, 1.5, 2.0),
) -> dict:
    """Compare runner parameter scenarios on the same recorded premium path.

    This is a path replay, not a predictive backtest. It does not optimize live
    parameters or modify any production trade monitor.
    """
    scenarios = []
    for activation in activation_pcts:
        for atr_multiple in atr_multiples:
            result = simulate_runner(
                path, entry, initial_stop, quantity, brokerage,
                activation_pct=float(activation), atr_multiple=float(atr_multiple),
            )
            scenarios.append({
                "activation_pct": float(activation),
                "atr_multiple": float(atr_multiple),
                **result,
            })
    valid = [item for item in scenarios if item.get("net_pnl") is not None]
    best = max(valid, key=lambda item: item["net_pnl"]) if valid else None
    return {
        "status": "READY" if valid else "INSUFFICIENT_RECORDED_PATH",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "best_observed_scenario": ({
            "activation_pct": best["activation_pct"],
            "atr_multiple": best["atr_multiple"],
            "net_pnl": best["net_pnl"],
            "net_return_pct": best["net_return_pct"],
        } if best else None),
        "comparison_basis": "SAME_RECORDED_OPTION_PREMIUM_PATH",
        "safety": "SIMULATION_ONLY",
        "warning": "Highest replay P&L is an in-sample path result, not evidence of future performance or a production parameter recommendation.",
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
