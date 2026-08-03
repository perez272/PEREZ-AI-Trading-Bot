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
        if last["close"] > last["VWAP"]:
            score += 10
        else:
            score -= 10
    except Exception:
        pass

    return max(0, min(score, 100))
