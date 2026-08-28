# MTF market-data contract

The scanner's M15/H1 confirmation uses EMA20, EMA50 and RSI14. The H1 EMA50 therefore requires at least 50 hourly bars, which cannot be produced from a single trading session of 5-minute candles.

For the 5-minute scanner feed, the Upstox historical fallback must provide enough multi-day history. A 15-calendar-day lookback is the minimum production default and is intentionally enforced even if `UPSTOX_HISTORICAL_LOOKBACK_DAYS` is set lower.

The scanner still removes the current, unclosed candle before indicators and integrity checks. No integrity threshold is weakened and no synthetic candles are created.
