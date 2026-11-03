"""NIFTY expiry-day rapid-move entry validation.

Pure, fail-closed strategy rules. This module does not place orders or size risk.
Input candles are completed 5-minute underlying-index candles.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import floor
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 30)
MAX_SPREAD_PCT = 0.80
MAX_EARLY_OPTION_MOVE_5M_PCT = 20.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _expiry_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y", "%d-%b-%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.upper(), fmt).date()
        except ValueError:
            continue
    return None


def _next_weekday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def is_expiry_session(expiry: Any, now: datetime | None = None) -> bool:
    """Allow the actual expiry date or the preceding weekday session.

    Weekends are handled. Exchange holidays are not inferred; the caller must
    fail closed if the exchange calendar says the expected session is closed.
    """
    now = (now or datetime.now(IST)).astimezone(IST)
    expiry_day = _expiry_date(expiry)
    return bool(expiry_day and expiry_day in {now.date(), _next_weekday(now.date())})


def _completed_5m(candles: list[Any], now: datetime) -> list[dict[str, float | datetime]]:
    rows = []
    for row in candles or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        stamp = _timestamp(row[0])
        if stamp is None or stamp + timedelta(minutes=5) > now:
            continue
        try:
            o, h, low, close, volume = (float(row[i]) for i in range(1, 6))
        except (TypeError, ValueError, IndexError):
            continue
        if min(o, h, low, close, volume) < 0 or close <= 0 or h < max(o, low, close) or low > min(o, h, close):
            continue
        rows.append({"time": stamp, "open": o, "high": h, "low": low, "close": close, "volume": volume})
    rows.sort(key=lambda item: item["time"])
    # Keep only the latest observation for a duplicate timestamp.
    unique = {item["time"]: item for item in rows}
    return [unique[key] for key in sorted(unique)]


def _completed_15m(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, float | datetime]]:
    grouped: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        stamp = row["time"]
        bucket = stamp.replace(minute=(stamp.minute // 15) * 15, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(row)
    result = []
    for bucket, parts in sorted(grouped.items()):
        parts.sort(key=lambda item: item["time"])
        expected = [bucket + timedelta(minutes=offset) for offset in (0, 5, 10)]
        if [part["time"] for part in parts] != expected or bucket + timedelta(minutes=15) > now:
            continue
        result.append({
            "time": bucket,
            "open": parts[0]["open"],
            "high": max(part["high"] for part in parts),
            "low": min(part["low"] for part in parts),
            "close": parts[-1]["close"],
            "volume": sum(part["volume"] for part in parts),
        })
    return result


def _ema(values: list[float], span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1.0 - alpha) * current
    return current


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _result(eligible: bool, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {"eligible": eligible, "reasons": reasons, **extra}


def evaluate_nifty_expiry_setup(
    candles: list[Any],
    *,
    symbol: str,
    option_type: str,
    expiry: Any,
    strike: float,
    option_move_1m_pct: float,
    option_move_3m_pct: float,
    option_move_5m_pct: float,
    spread_pct: float,
    option_volume: float,
    option_oi: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate all explicitly specified expiry-day rapid-move entry conditions."""
    now = (now or datetime.now(IST)).astimezone(IST)
    symbol = str(symbol or "").upper().strip()
    option_type = str(option_type or "").upper().strip()
    reasons: list[str] = []

    if symbol != "NIFTY":
        reasons.append("NIFTY_ONLY")
    if option_type not in {"CE", "PE"}:
        reasons.append("INVALID_OPTION_TYPE")
    if now.weekday() >= 5 or not ENTRY_START <= now.time() <= LAST_ENTRY:
        reasons.append("OUTSIDE_EXPIRY_ENTRY_WINDOW")
    if not is_expiry_session(expiry, now):
        reasons.append("NOT_EXPIRY_OR_PRE_EXPIRY_SESSION")

    rows = _completed_5m(candles, now)
    if len(rows) < 51:
        reasons.append("INSUFFICIENT_COMPLETED_5M_HISTORY")
        return _result(False, reasons, bars=len(rows))

    latest = rows[-1]
    age = (now - (latest["time"] + timedelta(minutes=5))).total_seconds()
    if age < 0 or age > 300:
        reasons.append("STALE_5M_SIGNAL")

    closes = [float(row["close"]) for row in rows]
    ema20 = _ema(closes[-100:], 20)
    ema50 = _ema(closes[-100:], 50)
    rsi14 = _rsi(closes, 14)
    volume_baseline = sum(float(row["volume"]) for row in rows[-21:-1]) / 20.0
    volume_ratio = float(latest["volume"]) / volume_baseline if volume_baseline > 0 else 0.0

    bars15 = _completed_15m(rows, now)
    if len(bars15) < 2:
        reasons.append("INSUFFICIENT_COMPLETED_15M_HISTORY")
        breakout_level = None
    else:
        previous_15m = bars15[-2]
        latest_15m = bars15[-1]
        breakout_level = float(previous_15m["high"] if option_type == "CE" else previous_15m["low"])
        breakout = (
            float(latest_15m["close"]) > breakout_level
            if option_type == "CE"
            else float(latest_15m["close"]) < breakout_level
        )
        if not breakout:
            reasons.append("15M_BREAKOUT_CLOSE_MISSING")

    if option_type == "CE":
        if not (ema20 > ema50 and float(latest["close"]) > ema20):
            reasons.append("BULLISH_EMA_ALIGNMENT_MISSING")
        if rsi14 is None or rsi14 <= 55.0:
            reasons.append("RSI14_NOT_ABOVE_55")
        body = float(latest["close"]) - float(latest["open"])
        upper_wick = float(latest["high"]) - max(float(latest["open"]), float(latest["close"]))
        if body <= 0 or upper_wick > 0.5 * body:
            reasons.append("CALL_CANDLE_WICK_TOO_LARGE")
    elif option_type == "PE":
        if not (ema20 < ema50 and float(latest["close"]) < ema20):
            reasons.append("BEARISH_EMA_ALIGNMENT_MISSING")
        if rsi14 is None or rsi14 >= 45.0:
            reasons.append("RSI14_NOT_BELOW_45")
        body = float(latest["open"]) - float(latest["close"])
        lower_wick = min(float(latest["open"]), float(latest["close"])) - float(latest["low"])
        if body <= 0 or lower_wick > 0.5 * body:
            reasons.append("PUT_CANDLE_WICK_TOO_LARGE")

    if volume_ratio < 1.5:
        reasons.append("VOLUME_BELOW_1_5X_PRIOR_20")
    if _number(option_move_1m_pct) <= 0 or _number(option_move_3m_pct) <= 0:
        reasons.append("OPTION_PREMIUM_NOT_CONFIRMED")
    if _number(option_move_5m_pct) >= MAX_EARLY_OPTION_MOVE_5M_PCT:
        reasons.append("OPTION_MOVE_OVEREXTENDED")
    if _number(spread_pct, 999.0) > MAX_SPREAD_PCT:
        reasons.append("WIDE_OPTION_SPREAD")
    if _number(option_volume) <= 0:
        reasons.append("NO_OPTION_VOLUME")
    if _number(option_oi) <= 0:
        reasons.append("NO_OPTION_OI")

    spot = float(latest["close"])
    atm = floor((spot / 50.0) + 0.5) * 50.0
    strike_value = _number(strike)
    allowed_strikes = {atm, atm - 50.0} if option_type == "CE" else {atm, atm + 50.0}
    if strike_value not in allowed_strikes:
        reasons.append("STRIKE_NOT_ATM_OR_ONE_ITM")

    return _result(
        not reasons,
        reasons,
        bars=len(rows),
        bars_15m=len(bars15),
        ema20=round(ema20, 4),
        ema50=round(ema50, 4),
        rsi14=round(rsi14, 4) if rsi14 is not None else None,
        volume_ratio=round(volume_ratio, 4),
        breakout_level=breakout_level,
        latest_5m_close=spot,
        signal_time=latest["time"].isoformat(),
        quote_age_seconds=round(age, 2),
    )
