"""Transparent ensemble scoring for PEREZ AI.

Combines existing evidence; it does not place orders and cannot bypass risk
controls. Scores are normalized to 0-100 and are intended for ranking only.
"""

WEIGHTS = {
    "market": 0.20,
    "momentum": 0.15,
    "breakout": 0.15,
    "mean_reversion": 0.10,
    "volume": 0.10,
    "volatility": 0.10,
    "regime": 0.10,
    "options": 0.05,
    "learned": 0.05,
}


def _clamp(value):
    return max(0.0, min(100.0, float(value or 0)))


def ensemble_score(candidate, options_score=0, learned_confidence=50, regime_bonus=50):
    base = _clamp(candidate.get("score", 0))
    momentum = _clamp(candidate.get("momentum_score", base))
    breakout = _clamp(candidate.get("breakout_score", base))
    mean_reversion = _clamp(candidate.get("mean_reversion_score", 50))
    volume = _clamp(candidate.get("volume_score", candidate.get("volume_ratio", 0) * 50))
    volatility = _clamp(candidate.get("volatility_score", 50))
    options = _clamp(options_score)
    learned = _clamp(learned_confidence)
    regime = _clamp(regime_bonus)

    values = {
        "market": base,
        "momentum": momentum,
        "breakout": breakout,
        "mean_reversion": mean_reversion,
        "volume": volume,
        "volatility": volatility,
        "regime": regime,
        "options": options,
        "learned": learned,
    }
    score = sum(values[k] * WEIGHTS[k] for k in WEIGHTS)
    return round(_clamp(score), 2), values


def decision_band(score):
    score = float(score)
    if score >= 90:
        return "EXCEPTIONAL"
    if score >= 80:
        return "HIGH_CONVICTION"
    if score >= 70:
        return "PAPER_CANDIDATE"
    if score >= 60:
        return "WATCH"
    return "NO_TRADE"
