def calculate_score(df):

    last = df.iloc[-1]

    score = 50

    if last["close"] > last["EMA20"]:
        score += 10
    else:
        score -= 10

    if last["EMA20"] > last["EMA50"]:
        score += 10
    else:
        score -= 10

    if last["EMA50"] > last["EMA200"]:
        score += 10
    else:
        score -= 10

    if last["MACD"] > last["MACD_SIGNAL"]:
        score += 10
    else:
        score -= 10

    if last["RSI"] > 60:
        score += 10
    elif last["RSI"] < 40:
        score -= 10

    try:
        vwap = last["VWAP"]
        if vwap == vwap:
            if last["close"] > vwap:
                score += 10
            else:
                score -= 10
    except Exception:
        pass

    return max(0, min(score, 100))


def calculate_directional_score(df, direction):
    """Score the six market components in the requested direction."""

    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError("direction must be BULLISH or BEARISH")

    last = df.iloc[-1]
    score = 50

    if direction == "BULLISH":
        if last["close"] > last["EMA20"]:
            score += 10
        else:
            score -= 10

        if last["EMA20"] > last["EMA50"]:
            score += 10
        else:
            score -= 10

        if last["EMA50"] > last["EMA200"]:
            score += 10
        else:
            score -= 10

        if last["MACD"] > last["MACD_SIGNAL"]:
            score += 10
        else:
            score -= 10

        if last["RSI"] > 60:
            score += 10
        elif last["RSI"] < 40:
            score -= 10

        try:
            vwap = last["VWAP"]
            if vwap == vwap:
                if last["close"] > vwap:
                    score += 10
                else:
                    score -= 10
        except Exception:
            pass

    else:
        if last["close"] < last["EMA20"]:
            score += 10
        else:
            score -= 10

        if last["EMA20"] < last["EMA50"]:
            score += 10
        else:
            score -= 10

        if last["EMA50"] < last["EMA200"]:
            score += 10
        else:
            score -= 10

        if last["MACD"] < last["MACD_SIGNAL"]:
            score += 10
        else:
            score -= 10

        if last["RSI"] < 40:
            score += 10
        elif last["RSI"] > 60:
            score -= 10

        try:
            vwap = last["VWAP"]
            if vwap == vwap:
                if last["close"] < vwap:
                    score += 10
                else:
                    score -= 10
        except Exception:
            pass

    return max(0, min(score, 100))
