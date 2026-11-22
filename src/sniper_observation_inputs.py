"""Fail-closed derivation of Sniper inputs from real market observations.

This module does not fetch data, infer missing values, or authorize trades. Callers
must supply timestamped one-minute underlying candles and cumulative option-volume
snapshots from the authenticated provider.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
ORB_END = time(9, 30)
MAX_CANDLE_AGE_SECONDS = 120


def _dt(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number > 0 and number < float("inf") else None
    except (TypeError, ValueError):
        return None


def build_underlying_context(
    candles: list[list[Any]], observed_at: str | datetime,
    max_age_seconds: int = MAX_CANDLE_AGE_SECONDS,
) -> dict[str, Any]:
    """Derive ORB/session breakout and 1m/3m/5m close momentum from 1m candles.

    Candle rows use [timestamp, open, high, low, close, volume]. Only completed,
    same-session candles are accepted. The current candle is excluded.
    """
    now = _dt(observed_at)
    empty = {
        "orb_breakout": False, "session_extreme_breakout": False,
        "breakout_direction": None, "breakout_level": None,
        "mtf_moves_pct": {}, "underlying_input_status": "INSUFFICIENT_OR_STALE",
        "underlying_observed_at": None,
    }
    if now is None or not isinstance(candles, list):
        return empty
    parsed = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        stamp = _dt(row[0])
        values = [_positive(row[i]) for i in (1, 2, 3, 4)]
        if stamp is None or any(value is None for value in values):
            continue
        op, high, low, close = values
        if high < max(op, low, close) or low > min(op, high, close):
            continue
        # Upstox minute candle timestamps denote the candle start.
        if stamp + timedelta(minutes=1) > now:
            continue
        if stamp.date() != now.date() or not (SESSION_OPEN <= stamp.time() < time(15, 30)):
            continue
        parsed.append((stamp, op, high, low, close))
    parsed.sort(key=lambda item: item[0])
    # Deduplicate timestamp collisions deterministically.
    by_stamp = {item[0]: item for item in parsed}
    bars = list(by_stamp.values())
    if not bars:
        return empty
    age = (now - (bars[-1][0] + timedelta(minutes=1))).total_seconds()
    if age < 0 or age > max(0, int(max_age_seconds)):
        return {**empty, "underlying_observed_at": bars[-1][0].isoformat(),
                "underlying_candle_age_seconds": round(age, 1)}
    closes = [bar[4] for bar in bars]
    if len(closes) < 6:
        return {**empty, "underlying_observed_at": bars[-1][0].isoformat(),
                "underlying_candle_age_seconds": round(age, 1)}
    latest = bars[-1]
    momentum = {}
    for label, periods in (("1m", 1), ("3m", 3), ("5m", 5)):
        prior = closes[-(periods + 1)]
        momentum[label] = round((latest[4] - prior) / prior * 100.0, 6) if prior > 0 else None

    session_bars = [bar for bar in bars if bar[0].time() >= SESSION_OPEN]
    orb_bars = [bar for bar in session_bars if SESSION_OPEN <= bar[0].time() < ORB_END]
    orb_ready = len(orb_bars) >= 15 and latest[0].time() >= ORB_END
    orb_high = max((bar[2] for bar in orb_bars), default=None) if orb_ready else None
    orb_low = min((bar[3] for bar in orb_bars), default=None) if orb_ready else None
    prior_bars = session_bars[:-1]
    prior_high = max((bar[2] for bar in prior_bars), default=None)
    prior_low = min((bar[3] for bar in prior_bars), default=None)
    close = latest[4]
    direction = None
    level = None
    orb = False
    extreme = False
    if orb_ready and orb_high is not None and close > orb_high:
        direction, level, orb = "CE", orb_high, True
    elif orb_ready and orb_low is not None and close < orb_low:
        direction, level, orb = "PE", orb_low, True
    elif prior_high is not None and close > prior_high:
        direction, level, extreme = "CE", prior_high, True
    elif prior_low is not None and close < prior_low:
        direction, level, extreme = "PE", prior_low, True

    return {
        "orb_breakout": orb,
        "session_extreme_breakout": extreme,
        "breakout_direction": direction,
        "breakout_level": level,
        "mtf_moves_pct": momentum,
        "underlying_input_status": "READY",
        "underlying_observed_at": latest[0].isoformat(),
        "underlying_candle_age_seconds": round(age, 1),
        "orb_high": orb_high, "orb_low": orb_low,
        "session_prior_high": prior_high, "session_prior_low": prior_low,
        "safety": "OBSERVATION_ONLY",
    }


def option_volume_expansion(
    cumulative_volume_points: list[dict[str, Any]],
    minimum_baseline_intervals: int = 5,
) -> dict[str, Any]:
    """Compare latest one-minute volume delta with prior interval deltas.

    Input points must be chronological cumulative session-volume observations
    for the same option contract, at one-minute cadence. Resets and gaps fail closed.
    """
    points = []
    for item in cumulative_volume_points or []:
        if not isinstance(item, dict):
            continue
        stamp = _dt(item.get("observed_at"))
        volume = _positive(item.get("volume"))
        if stamp is not None and volume is not None:
            points.append((stamp, volume))
    points.sort(key=lambda item: item[0])
    deduped = {stamp: volume for stamp, volume in points}
    points = list(deduped.items())
    needed = max(2, int(minimum_baseline_intervals) + 1)
    if len(points) < needed + 1:
        return {"volume_ratio": None, "status": "INSUFFICIENT_VOLUME_HISTORY"}
    deltas = []
    for (previous_ts, previous_volume), (current_ts, current_volume) in zip(points, points[1:]):
        seconds = (current_ts - previous_ts).total_seconds()
        delta = current_volume - previous_volume
        if not 45 <= seconds <= 90 or delta < 0:
            return {"volume_ratio": None, "status": "VOLUME_HISTORY_GAP_OR_RESET"}
        deltas.append(delta)
    baseline = median(deltas[:-1][-minimum_baseline_intervals:])
    if baseline <= 0:
        return {"volume_ratio": None, "status": "ZERO_VOLUME_BASELINE"}
    ratio = deltas[-1] / baseline
    return {
        "volume_ratio": round(ratio, 4),
        "latest_interval_volume": deltas[-1],
        "baseline_interval_volume": round(baseline, 4),
        "status": "READY",
        "safety": "OBSERVATION_ONLY",
    }
