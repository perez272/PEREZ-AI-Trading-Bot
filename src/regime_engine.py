"""Deterministic market-regime classifier for PEREZ AI.

The classifier is deliberately conservative: it labels conditions from the
features already produced by the scanner and never creates a trade by itself.
"""


def classify_regime(candidate):
    score = float(candidate.get("score", 0) or 0)
    trend = str(candidate.get("trend", "")).lower()
    volume = float(candidate.get("volume_ratio", 0) or 0)
    rsi = float(candidate.get("rsi", 50) or 50)
    volatility = float(candidate.get("volatility_score", candidate.get("atr_pct", 0)) or 0)

    if "bull" in trend or "up" in trend:
        direction = "BULLISH"
    elif "bear" in trend or "down" in trend:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    if volatility >= 8 or volume >= 2.0:
        vol = "HIGH_VOLATILITY"
    elif volatility <= 2 and volume < 0.8:
        vol = "LOW_VOLATILITY"
    else:
        vol = "NORMAL_VOLATILITY"

    if score >= 70 and direction != "NEUTRAL":
        structure = "TRENDING"
    elif 45 <= score < 70:
        structure = "MIXED"
    else:
        structure = "RANGING_OR_WEAK"

    return f"{direction}|{structure}|{vol}"


def regime_summary(candidate):
    regime = classify_regime(candidate)
    direction, structure, volatility = regime.split("|", 2)
    return {
        "regime": regime,
        "direction": direction,
        "structure": structure,
        "volatility": volatility,
    }
