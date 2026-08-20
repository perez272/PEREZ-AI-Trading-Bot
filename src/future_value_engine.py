"""PEREZ AI Future Value Engine.

A probability/range estimator for already-selected market candidates.
It deliberately avoids pretending that an exact future price is knowable.
All unavailable evidence is treated as neutral or blocking where safety
requires it; fabricated news, IV, Greeks, OI-change, or price targets are
never generated.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any, Dict, Iterable, Mapping


@dataclass(frozen=True)
class Forecast:
    symbol: str
    asset_type: str
    horizon: str
    direction: str
    probability_up: float
    probability_down: float
    confidence: float
    current_price: float
    expected_low: float
    expected_high: float
    target: float
    invalidation: float
    regime: str
    drivers: tuple[str, ...]
    blockers: tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _component(value: Any, center: float = 50.0) -> float:
    """Convert a 0..100 component into a centred -1..1 contribution."""
    return _clamp((_num(value, center) - center) / 50.0, -1.0, 1.0)


def _weighted_signal(candidate: Mapping[str, Any], news: Mapping[str, Any]) -> tuple[float, list[str], list[str]]:
    """Score independent evidence families; missing evidence stays neutral."""
    weights = {
        "trend_score": 0.18,
        "momentum_score": 0.14,
        "volume_score": 0.10,
        "vwap_score": 0.10,
        "structure_score": 0.10,
        "volatility_score": 0.07,
        "index_confirmation": 0.10,
        "oi_score": 0.06,
        "oi_change_score": 0.05,
        "iv_score": 0.04,
        "liquidity_score": 0.06,
    }
    signal = 0.0
    used = 0.0
    drivers: list[str] = []
    blockers: list[str] = []

    for key, weight in weights.items():
        if key not in candidate:
            continue
        raw = _num(candidate.get(key), 50.0)
        signal += _component(raw) * weight
        used += weight
        if raw >= 65:
            drivers.append(key.replace("_", " "))
        elif raw <= 35:
            blockers.append(key.replace("_", " "))

    news_score = _num(news.get("score"), 50.0)
    if news.get("available") is True:
        signal += _component(news_score) * 0.10
        used += 0.10
        if news_score >= 65:
            drivers.append("news confirmation")
        elif news_score <= 35:
            blockers.append("negative news")
    else:
        blockers.append("news unavailable")

    penalty = _num(candidate.get("event_risk_penalty"), 0.0)
    signal -= _clamp(penalty / 100.0, 0.0, 1.0) * 0.15
    used = max(used, 0.01)
    return _clamp(signal / used, -1.0, 1.0), drivers, blockers


def forecast(candidate: Mapping[str, Any], *, horizon: str = "2h", news: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Return a conservative probability/range forecast for one selected candidate."""
    news = news or {}
    symbol = str(candidate.get("symbol") or candidate.get("underlying") or "").strip().upper()
    price = _num(candidate.get("ltp") or candidate.get("close") or candidate.get("entry"))
    if not symbol or price <= 0:
        return {"eligible": False, "reason": "INVALID_CANDIDATE"}

    signal, drivers, blockers = _weighted_signal(candidate, news)
    direction = "BULLISH" if signal > 0.12 else "BEARISH" if signal < -0.12 else "NEUTRAL"

    atr_pct = _num(candidate.get("atr_pct") or candidate.get("volatility_pct"), 1.5)
    atr_pct = _clamp(atr_pct, 0.25, 8.0)
    horizon_multiplier = {"30m": 0.65, "2h": 1.0, "1d": 1.6, "5d": 2.5}.get(horizon, 1.0)
    expected_move = price * (atr_pct / 100.0) * horizon_multiplier
    expected_move *= 0.75 + abs(signal) * 0.75

    confidence = 50.0 + abs(signal) * 35.0
    if news.get("available") is True:
        confidence += 5.0
    if blockers:
        confidence -= min(15.0, len(blockers) * 2.5)
    confidence = _clamp(confidence, 0.0, 95.0)

    target = price + expected_move if direction == "BULLISH" else price - expected_move if direction == "BEARISH" else price
    invalidation = price - expected_move * 0.65 if direction == "BULLISH" else price + expected_move * 0.65 if direction == "BEARISH" else price

    return {
        "eligible": True,
        "forecast": Forecast(
            symbol=symbol,
            asset_type=str(candidate.get("asset_type", "equity")),
            horizon=horizon,
            direction=direction,
            probability_up=round(_clamp(50.0 + signal * 50.0, 1.0, 99.0), 2),
            probability_down=round(_clamp(50.0 - signal * 50.0, 1.0, 99.0), 2),
            confidence=round(confidence, 2),
            current_price=round(price, 4),
            expected_low=round(max(0.0, price - expected_move), 4),
            expected_high=round(price + expected_move, 4),
            target=round(max(0.0, target), 4),
            invalidation=round(max(0.0, invalidation), 4),
            regime=direction,
            drivers=tuple(dict.fromkeys(drivers))[:8],
            blockers=tuple(dict.fromkeys(blockers))[:8],
        ).as_dict(),
    }


def rank_selected(candidates: Iterable[Mapping[str, Any]], *, news_by_symbol: Mapping[str, Mapping[str, Any]] | None = None, horizon: str = "2h") -> list[Dict[str, Any]]:
    """Rank only the caller-provided/selected universe; never expand it implicitly."""
    news_by_symbol = news_by_symbol or {}
    output = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or candidate.get("underlying") or "").upper()
        result = forecast(candidate, horizon=horizon, news=news_by_symbol.get(symbol, {}))
        if result.get("eligible"):
            output.append(result["forecast"])
    return sorted(output, key=lambda x: (x["confidence"], abs(x["probability_up"] - 50.0)), reverse=True)
