def get_trade_decision(score, rsi, ema20, ema50, close):

    # Strong Bullish
    if close > ema20 > ema50:
        if score >= 60 and rsi >= 55:
            return "BUY CE", "STRONG BULLISH"

    # Bullish
    if close > ema20 and score >= 50:
        return "BUY CE", "BULLISH"

    # Strong Bearish
    if close < ema20 < ema50:
        if rsi <= 45:
            return "BUY PE", "STRONG BEARISH"

    # Bearish
    if close < ema20:
        return "BUY PE", "BEARISH"

    return "NO TRADE", "WAIT"
