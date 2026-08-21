"""Explainable, defensive trade scoring.

The public ``calculate_score`` API is preserved for compatibility.  The richer
``score_setup`` API exposes component evidence so the trading engine can make
measurable decisions instead of treating one opaque number as intelligence.
"""


def _clamp(value, low=0, high=100):
    return max(low, min(int(round(value)), high))


def score_setup(df):
    """Return ``score``, ``bias`` and component evidence for the last closed bar.

    Missing optional fields do not crash the scanner.  A setup is deliberately
    conservative when core trend fields are unavailable.
    """
    if df is None or len(df) == 0:
        return {"score": 0, "bias": "UNKNOWN", "confidence": 0, "components": {}}

    last = df.iloc[-1]
    required = ("close", "EMA20", "EMA50", "EMA200", "MACD", "MACD_SIGNAL", "RSI")
    if any(field not in last.index for field in required):
        return {"score": 0, "bias": "UNKNOWN", "confidence": 0, "components": {}}

    close = float(last["close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema200 = float(last["EMA200"])
    macd = float(last["MACD"])
    macd_signal = float(last["MACD_SIGNAL"])
    rsi = float(last["RSI"])

    bullish = 50
    bearish = 50
    components = {}

    def add(name, bull, bear):
        nonlocal bullish, bearish
        bullish += bull
        bearish += bear
        components[name] = {"bull": bull, "bear": bear}

    add("price_vs_ema20", 12 if close > ema20 else 0, 12 if close < ema20 else 0)
    add("ema_stack", 15 if ema20 > ema50 > ema200 else 0,
        15 if ema20 < ema50 < ema200 else 0)
    add("macd", 10 if macd > macd_signal else 0,
        10 if macd < macd_signal else 0)

    if 50 <= rsi <= 68:
        add("rsi", 10, 0)
    elif 32 <= rsi <= 50:
        add("rsi", 0, 10)
    elif rsi > 75:
        add("rsi_overextended", 0, 5)
    elif rsi < 25:
        add("rsi_overextended", 5, 0)

    vwap = last.get("VWAP")
    if vwap is not None:
        try:
            vwap = float(vwap)
            add("vwap", 8 if close > vwap else 0, 8 if close < vwap else 0)
        except (TypeError, ValueError):
            pass

    volume_ratio = last.get("volume_ratio")
    if volume_ratio is not None:
        try:
            vr = float(volume_ratio)
            if vr >= 1.5:
                add("volume_confirmation", 7 if close >= ema20 else 0,
                    7 if close < ema20 else 0)
        except (TypeError, ValueError):
            pass

    # Penalise a conflicting trend rather than rewarding isolated indicators.
    if close > ema20 and ema20 < ema50:
        bullish -= 8
    if close < ema20 and ema20 > ema50:
        bearish -= 8

    if bullish > bearish + 10:
        bias = "BULLISH"
    elif bearish > bullish + 10:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    score = _clamp(max(bullish, bearish))
    confidence = _clamp(abs(bullish - bearish) * 2)
    return {
        "score": score,
        "bias": bias,
        "confidence": confidence,
        "components": components,
    }


def calculate_score(df):
    """Backward-compatible 0-100 score used by existing scanners."""
    return score_setup(df)["score"]
