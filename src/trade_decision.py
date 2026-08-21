"""Deterministic trade decision gate.

The gate intentionally prefers ``NO TRADE`` when evidence conflicts.  It does
not place orders; it only converts validated market evidence into a decision.
"""


def _finite_positive(value):
    try:
        value = float(value)
        return value > 0
    except (TypeError, ValueError):
        return False


def get_trade_decision(
    score,
    rsi,
    ema20,
    ema50,
    close,
    ema200=None,
    atr=None,
    previous_high=None,
    previous_low=None,
    volume_ratio=None,
):
    """Return ``(decision, reason)`` using trend, momentum and risk gates.

    Legacy arguments remain accepted.  Breakout and volatility evidence is now
    used when supplied, while insufficient evidence results in ``NO TRADE``.
    """
    try:
        score = float(score)
        rsi = float(rsi)
        ema20 = float(ema20)
        ema50 = float(ema50)
        close = float(close)
    except (TypeError, ValueError):
        return "NO TRADE", "INVALID INPUT"

    if not all(_finite_positive(v) for v in (close, ema20, ema50)):
        return "NO TRADE", "INVALID PRICE DATA"

    # Avoid chasing extremely stretched RSI readings unless a breakout has
    # meaningful volume confirmation.
    volume_ok = False
    if volume_ratio is not None:
        try:
            volume_ok = float(volume_ratio) >= 1.25
        except (TypeError, ValueError):
            volume_ok = False

    bullish = close > ema20 > ema50
    bearish = close < ema20 < ema50

    if ema200 is not None:
        try:
            ema200 = float(ema200)
            bullish = bullish and ema20 > ema200
            bearish = bearish and ema20 < ema200
        except (TypeError, ValueError):
            return "NO TRADE", "INVALID EMA200"

    breakout_up = previous_high is not None and close > float(previous_high)
    breakout_down = previous_low is not None and close < float(previous_low)

    if atr is not None:
        try:
            atr = float(atr)
            if atr <= 0 or atr > close * 0.12:
                return "NO TRADE", "ABNORMAL VOLATILITY"
        except (TypeError, ValueError):
            return "NO TRADE", "INVALID ATR"

    # Strong setup: aligned trend + momentum + sufficient score.
    if bullish and score >= 72 and 52 <= rsi <= 72:
        if rsi > 68 and not (breakout_up and volume_ok):
            return "NO TRADE", "BULLISH BUT OVEREXTENDED"
        if breakout_up and volume_ratio is not None and not volume_ok:
            return "NO TRADE", "BREAKOUT WITHOUT VOLUME"
        return "BUY CE", "HIGH-CONVICTION BULLISH"

    if bearish and score >= 72 and 28 <= rsi <= 48:
        if rsi < 32 and not (breakout_down and volume_ok):
            return "NO TRADE", "BEARISH BUT OVEREXTENDED"
        if breakout_down and volume_ratio is not None and not volume_ok:
            return "NO TRADE", "BREAKDOWN WITHOUT VOLUME"
        return "BUY PE", "HIGH-CONVICTION BEARISH"

    # Moderate setups require stronger directional confirmation.
    if bullish and score >= 62 and rsi >= 55:
        return "BUY CE", "CONFIRMED BULLISH"
    if bearish and score >= 62 and rsi <= 45:
        return "BUY PE", "CONFIRMED BEARISH"

    return "NO TRADE", "INSUFFICIENT CONFLUENCE"
