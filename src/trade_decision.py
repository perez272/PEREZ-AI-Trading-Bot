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
    """Return a CE/PE decision while supporting legacy scanner arguments."""
    del ema200, atr, previous_high, previous_low, volume_ratio

    if close > ema20 > ema50:
        if score >= 60 and rsi >= 55:
            return "BUY CE", "STRONG BULLISH"

    if close > ema20 and score >= 50:
        return "BUY CE", "BULLISH"

    if close < ema20 < ema50:
        if rsi <= 45:
            return "BUY PE", "STRONG BEARISH"

    if close < ema20:
        return "BUY PE", "BEARISH"

    return "NO TRADE", "WAIT"
