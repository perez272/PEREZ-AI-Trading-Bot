import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision

from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.optionable_universe import get_optionable_universe
from src.data_cache import load_cache, save_cache, cache_valid


# ============================================================
# PEREZ AI HYPE / MOMENTUM SCANNER
# ============================================================

SCAN_INTERVAL = 300

# Small pacing delay between candle requests.
# AngelClient handles rate-limit backoff separately.
API_PACING_DELAY = 1.00

# ============================================================
# STEP20B — FAST CACHE-FIRST SCANNER
# ============================================================

# Never make more than this many historical-data API
# refreshes during one complete 210-symbol scan.
MAX_API_REFRESHES_PER_SCAN = 0

# Persistent cache is accepted when it is <= 5 minutes old.
CACHE_MAX_AGE_MINUTES = 5


CANDLE_CACHE = {}
CACHE_EXPIRY = 600

_session = None
_client = None


def get_client():
    global _session, _client

    if _client is None:
        _session = SessionManager(
            API_KEY,
            CLIENT_ID,
            PASSWORD,
            TOTP_SECRET,
        )

        _client = AngelClient(
            _session.get_client()
        )

    return _client


def get_universe():
    """
    Returns all NSE equity symbols that have F&O options.

    optionable_universe.get_optionable_universe()
    returns:
        {
            "SYMBOL": {
                "name": "...",
                "symbol": "...-EQ",
                "token": "...",
                "exchange": "NSE"
            }
        }
    """

    universe = get_optionable_universe()

    results = {}

    for symbol, item in universe.items():

        if not isinstance(item, dict):
            continue

        name = item.get("name") or symbol
        token = item.get("token")
        trading_symbol = item.get("symbol")
        exchange = item.get("exchange", "NSE")

        if not token or not trading_symbol:
            continue

        results[name] = (
            exchange,
            str(token),
            trading_symbol,
        )

    return results


# ============================================================
# COMPATIBILITY SYMBOL MAP
# ============================================================
# Legacy strategy/backtest modules expect:
#     SYMBOLS[symbol] = (exchange, token)
#
# The current scanner universe contains:
#     (exchange, token, trading_symbol)
#
# Keep one source of truth by deriving SYMBOLS from the
# current optionable universe instead of maintaining a
# separate hard-coded symbol list.
SYMBOLS = {
    symbol: (data[0], data[1])
    for symbol, data in get_universe().items()
    if isinstance(data, tuple) and len(data) >= 2
}


def get_candles(symbol, exchange, token):

    # --------------------------------------------------------
    # LEVEL 1: In-memory cache
    # --------------------------------------------------------

    cached = CANDLE_CACHE.get(symbol)

    if cached:

        age = time.time() - cached["time"]

        if age < CACHE_EXPIRY:

            return cached["data"]

    # --------------------------------------------------------
    # LEVEL 2: Persistent disk cache
    # --------------------------------------------------------

    try:

        if cache_valid(symbol, minutes=5):

            cached_obj = load_cache(symbol)

            if cached_obj:

                candles = cached_obj.get("data")

                if candles:

                    CANDLE_CACHE[symbol] = {
                        "data": candles,
                        "time": time.time(),
                    }

                    print(
                        f"{symbol}: persistent cache HIT"
                    )

                    return candles

    except Exception as e:

        print(
            f"{symbol}: persistent cache error -> {e}"
        )

    # --------------------------------------------------------
    # LEVEL 3: Angel One API
    # --------------------------------------------------------

    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": (
            now - timedelta(days=5)
        ).strftime("%Y-%m-%d %H:%M"),
        "todate": now.strftime(
            "%Y-%m-%d %H:%M"
        ),
    }

    try:

        response = get_client().get_candles(params)

        if not response:

            return None

        if not response.get("status"):

            return None

        candles = response.get("data")

        if not candles:

            return None

        # Memory cache
        CANDLE_CACHE[symbol] = {
            "data": candles,
            "time": time.time(),
        }

        # Persistent cache
        try:

            save_cache(
                symbol,
                candles
            )

        except Exception as e:

            print(
                f"{symbol}: cache save error -> {e}"
            )

        return candles

    except Exception as e:

        print(
            f"{symbol}: candle error -> {e}"
        )

        return None


def hype_score(df):

    if df.empty or len(df) < 30:
        return 0, {}

    last = df.iloc[-1]

    close = float(last["close"])

    score = 0

    details = {}

    # --------------------------------------------------------
    # 1. MOMENTUM
    # --------------------------------------------------------

    prev_close = float(
        df["close"].iloc[-2]
    )

    change_5m = (
        (close - prev_close)
        / prev_close
        * 100
    )

    details["change_5m"] = change_5m

    if change_5m >= 1.0:
        score += 20

    elif change_5m >= 0.5:
        score += 12

    elif change_5m >= 0.25:
        score += 6


    # --------------------------------------------------------
    # 2. VOLUME EXPANSION
    # --------------------------------------------------------

    avg_volume = (
        df["volume"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    volume = float(last["volume"])

    if avg_volume > 0:

        volume_ratio = (
            volume / avg_volume
        )

    else:
        volume_ratio = 0

    details["volume_ratio"] = volume_ratio

    if volume_ratio >= 4:
        score += 25

    elif volume_ratio >= 3:
        score += 20

    elif volume_ratio >= 2:
        score += 14

    elif volume_ratio >= 1.5:
        score += 7


    # --------------------------------------------------------
    # 3. BREAKOUT
    # --------------------------------------------------------

    previous_high = float(
        df["high"]
        .iloc[-21:-1]
        .max()
    )

    previous_low = float(
        df["low"]
        .iloc[-21:-1]
        .min()
    )

    details["previous_high"] = previous_high
    details["previous_low"] = previous_low

    if close > previous_high:
        score += 20
        details["breakout"] = "UP"

    elif close < previous_low:
        score += 20
        details["breakout"] = "DOWN"

    else:
        details["breakout"] = "NONE"


    # --------------------------------------------------------
    # 4. EMA TREND
    # --------------------------------------------------------

    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])

    details["ema20"] = ema20
    details["ema50"] = ema50

    if close > ema20 > ema50:
        score += 15
        details["trend"] = "BULLISH"

    elif close < ema20 < ema50:
        score += 15
        details["trend"] = "BEARISH"

    else:
        details["trend"] = "MIXED"


    # --------------------------------------------------------
    # 5. RSI
    # --------------------------------------------------------

    rsi = float(last["RSI"])

    details["rsi"] = rsi

    if 55 <= rsi <= 72:
        score += 10

    elif 45 <= rsi < 55:
        score += 4


    # --------------------------------------------------------
    # 6. ATR / RANGE EXPANSION
    # --------------------------------------------------------

    atr = float(last["ATR"])

    details["atr"] = atr

    if close > 0:

        atr_pct = (
            atr / close * 100
        )

    else:
        atr_pct = 0

    details["atr_pct"] = atr_pct

    if atr_pct >= 2:
        score += 10

    elif atr_pct >= 1:
        score += 5


    return min(score, 100), details


def _step21_cached_candles(symbol):
    """
    STEP21:
    Use persistent cache whenever candles exist.
    Freshness is handled by selective API refresh,
    not by rejecting the entire local dataset.
    """
    try:
        obj = load_cache(symbol)

        if not obj:
            return None

        candles = obj.get("data", [])

        if candles:
            return candles

    except Exception:
        pass

    return None


def scan_market():

    universe = get_universe()

    print(
        f"\nPEREZ AI HYPE RADAR"
    )

    print(
        f"OPTIONABLE NSE STOCKS: "
        f"{len(universe)}"
    )

    results = []

    # STEP20B counters
    api_refreshes = 0
    cached_count = 0
    skipped_count = 0

    for index, (
        symbol,
        data,
    ) in enumerate(universe.items(), 1):

        exchange, token, trading_symbol = data

        print(
            f"[{index}/{len(universe)}] "
            f"{symbol}",
            end=" ",
            flush=True,
        )

        # ====================================================
        # STEP20B — CACHE FIRST
        # ====================================================

        candles = _step21_cached_candles(symbol)

        if candles:
            cached_count += 1
            print("CACHE", end=" ", flush=True)

        else:
            # ================================================
            # STEP22 — CACHE ONLY
            # No API refresh when cache is unavailable.
            # ================================================

            skipped_count += 1
            print("NO CACHE — SKIP")
            continue

        if not candles:

            print("NO DATA")
            continue

        try:

            df = calculate_indicators(
                candles
            )

            if df.empty or len(df) < 30:

                print("INSUFFICIENT")
                continue

            last = df.iloc[-1]

            base_score = calculate_score(df)

            hype, details = hype_score(df)

            final_score = int(
                min(
                    100,
                    base_score * 0.4
                    + hype * 0.6
                )
            )

            signal, trend = get_trade_decision(
                final_score,
                float(last["RSI"]),
                float(last["EMA20"]),
                float(last["EMA50"]),
                float(last["close"]),
                float(last["EMA200"]),
                float(last["ATR"]),
                details["previous_high"],
                details["previous_low"],
                details["volume_ratio"],
            )

            result = {
                "symbol": symbol,
                "token": token,
                "trading_symbol": trading_symbol,
                "score": final_score,
                "hype_score": hype,
                "close": float(last["close"]),
                "rsi": float(last["RSI"]),
                "volume_ratio": details["volume_ratio"],
                "change_5m": details["change_5m"],
                "breakout": details["breakout"],
                "trend": trend,
                "signal": signal,
            }

            results.append(result)

            print(
                f"Score={final_score} "
                f"Hype={hype} "
                f"Vol={details['volume_ratio']:.2f} "
                f"5m={details['change_5m']:.2f}% "
                f"{signal}"
            )

        except Exception as e:

            print(
                f"ERROR={e}"
            )

        # Light API pacing.
        # AngelClient performs exponential backoff if
        # Angel One actually rate-limits a request.
        time.sleep(API_PACING_DELAY)

    print()
    print("=" * 70)
    print("STEP20B SCAN SUMMARY")
    print("=" * 70)
    print("UNIVERSE          :", len(universe))
    print("FRESH CACHE USED  :", cached_count)
    print("API REFRESHES     :", api_refreshes)
    print("SKIPPED API LIMIT :", skipped_count)
    print("RESULTS           :", len(results))
    print("=" * 70)

    results.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            abs(x["change_5m"]),
        ),
        reverse=True,
    )

    return results


def select_best_candidate(
    results,
    minimum_score=60,
):

    eligible = [

        x for x in results

        if x["score"] >= minimum_score

        and x["signal"]
        in ("BUY CE", "BUY PE")

        and x["volume_ratio"] >= 1.5

    ]

    return (
        eligible[0]
        if eligible
        else None
    )


def print_results(results):

    print("\n")
    print("=" * 100)
    print("PEREZ AI — TOP HYPE CANDIDATES")
    print("=" * 100)

    for item in results[:20]:

        print(
            f"{item['symbol']:<14}"
            f" SCORE={item['score']:>3}"
            f" HYPE={item['hype_score']:>3}"
            f" 5m={item['change_5m']:>6.2f}%"
            f" VOL={item['volume_ratio']:>5.2f}x"
            f" RSI={item['rsi']:>5.1f}"
            f" BREAK={item['breakout']:<4}"
            f" SIGNAL={item['signal']}"
        )

    print("=" * 100)


if __name__ == "__main__":

    results = scan_market()

    print_results(results)

    candidate = select_best_candidate(
        results,
        60,
    )

    print("\nBEST CANDIDATE:")

    if candidate:

        print(candidate)

    else:

        print(
            "NO HIGH-CONVICTION SETUP"
        )
