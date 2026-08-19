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

SCAN_INTERVAL = 300
API_PACING_DELAY = 1.00
MAX_API_REFRESHES_PER_SCAN = 0
CACHE_MAX_AGE_MINUTES = 5
CANDLE_CACHE = {}
CACHE_EXPIRY = CACHE_MAX_AGE_MINUTES * 60
_session = None
_client = None


def get_client():
    global _session, _client
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
    return _client


def get_universe():
    universe = get_optionable_universe()
    results = {}
    for symbol, item in universe.items():
        if not isinstance(item, dict):
            continue
        name = item.get("name") or symbol
        token = item.get("token")
        trading_symbol = item.get("symbol")
        exchange = item.get("exchange", "NSE")
        if token and trading_symbol:
            results[name] = (exchange, str(token), trading_symbol)
    return results


SYMBOLS = {
    symbol: (data[0], data[1])
    for symbol, data in get_universe().items()
    if isinstance(data, tuple) and len(data) >= 2
}


def _validate_candles(candles):
    """Reject empty/malformed candle sets and data with no recent candle."""
    if not isinstance(candles, list) or len(candles) < 30:
        return False
    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            return False
        raw_ts = str(last[0]).replace("Z", "+00:00")
        ts = datetime.fromisoformat(raw_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        now = datetime.now(ts.tzinfo)
        age = (now - ts).total_seconds()
        if age < -60 or age > 15 * 60:
            return False
        for value in last[1:6]:
            if float(value) < 0:
                return False
        return float(last[4]) > 0
    except (TypeError, ValueError, IndexError):
        return False


def get_candles(symbol, exchange, token):
    cached = CANDLE_CACHE.get(symbol)
    if cached and time.time() - cached["time"] <= CACHE_EXPIRY:
        if _validate_candles(cached["data"]):
            return cached["data"]
        CANDLE_CACHE.pop(symbol, None)

    try:
        if cache_valid(symbol, minutes=CACHE_MAX_AGE_MINUTES):
            cached_obj = load_cache(symbol)
            candles = cached_obj.get("data") if cached_obj else None
            if _validate_candles(candles):
                CANDLE_CACHE[symbol] = {"data": candles, "time": time.time()}
                return candles
    except Exception as e:
        print(f"{symbol}: persistent cache error -> {e}")

    if MAX_API_REFRESHES_PER_SCAN <= 0:
        return None

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M"),
        "todate": now.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        response = get_client().get_candles(params)
        candles = response.get("data") if response and response.get("status") else None
        if not _validate_candles(candles):
            return None
        CANDLE_CACHE[symbol] = {"data": candles, "time": time.time()}
        save_cache(symbol, candles)
        return candles
    except Exception as e:
        print(f"{symbol}: candle error -> {e}")
        return None


def _step21_cached_candles(symbol):
    """Return candles only when the persistent cache itself is fresh and valid."""
    try:
        if not cache_valid(symbol, minutes=CACHE_MAX_AGE_MINUTES):
            return None
        obj = load_cache(symbol)
        candles = obj.get("data", []) if obj else []
        return candles if _validate_candles(candles) else None
    except Exception:
        return None


def hype_score(df):
    if df.empty or len(df) < 30:
        return 0, {}
    last = df.iloc[-1]
    close = float(last["close"])
    score = 0
    details = {}
    prev_close = float(df["close"].iloc[-2])
    change_5m = (close - prev_close) / prev_close * 100
    details["change_5m"] = change_5m
    if change_5m >= 1.0: score += 20
    elif change_5m >= 0.5: score += 12
    elif change_5m >= 0.25: score += 6
    avg_volume = df["volume"].rolling(20).mean().iloc[-1]
    volume = float(last["volume"])
    volume_ratio = volume / avg_volume if avg_volume > 0 else 0
    details["volume_ratio"] = volume_ratio
    if volume_ratio >= 4: score += 25
    elif volume_ratio >= 3: score += 20
    elif volume_ratio >= 2: score += 14
    elif volume_ratio >= 1.5: score += 7
    previous_high = float(df["high"].iloc[-21:-1].max())
    previous_low = float(df["low"].iloc[-21:-1].min())
    details["previous_high"] = previous_high
    details["previous_low"] = previous_low
    if close > previous_high: score += 20; details["breakout"] = "UP"
    elif close < previous_low: score += 20; details["breakout"] = "DOWN"
    else: details["breakout"] = "NONE"
    ema20, ema50 = float(last["EMA20"]), float(last["EMA50"])
    details["ema20"], details["ema50"] = ema20, ema50
    if close > ema20 > ema50: score += 15; details["trend"] = "BULLISH"
    elif close < ema20 < ema50: score += 15; details["trend"] = "BEARISH"
    else: details["trend"] = "MIXED"
    rsi = float(last["RSI"]); details["rsi"] = rsi
    if 55 <= rsi <= 72: score += 10
    elif 45 <= rsi < 55: score += 4
    atr = float(last["ATR"]); details["atr"] = atr
    atr_pct = atr / close * 100 if close > 0 else 0
    details["atr_pct"] = atr_pct
    if atr_pct >= 2: score += 10
    elif atr_pct >= 1: score += 5
    return min(score, 100), details


def scan_market():
    universe = get_universe()
    print(f"\nPEREZ AI HYPE RADAR")
    print(f"OPTIONABLE NSE STOCKS: {len(universe)}")
    results = []
    cached_count = 0
    skipped_count = 0
    for index, (symbol, data) in enumerate(universe.items(), 1):
        exchange, token, trading_symbol = data
        print(f"[{index}/{len(universe)}] {symbol}", end=" ", flush=True)
        candles = _step21_cached_candles(symbol)
        if not candles:
            skipped_count += 1
            print("STALE/MISSING CACHE — SKIP")
            continue
        cached_count += 1
        print("FRESH CACHE", end=" ", flush=True)
        try:
            df = calculate_indicators(candles)
            if df.empty or len(df) < 30:
                print("INSUFFICIENT")
                continue
            last = df.iloc[-1]
            base_score = calculate_score(df)
            hype, details = hype_score(df)
            final_score = int(min(100, base_score * 0.4 + hype * 0.6))
            signal, trend = get_trade_decision(final_score, float(last["RSI"]), float(last["EMA20"]), float(last["EMA50"]), float(last["close"]), float(last["EMA200"]), float(last["ATR"]), details["previous_high"], details["previous_low"], details["volume_ratio"])
            results.append({"symbol": symbol, "token": token, "trading_symbol": trading_symbol, "score": final_score, "hype_score": hype, "close": float(last["close"]), "rsi": float(last["RSI"]), "volume_ratio": details["volume_ratio"], "change_5m": details["change_5m"], "breakout": details["breakout"], "trend": trend, "signal": signal})
            print(f"Score={final_score} Hype={hype} Vol={details['volume_ratio']:.2f} 5m={details['change_5m']:.2f}% {signal}")
        except Exception as e:
            print(f"ERROR={e}")
        time.sleep(API_PACING_DELAY)
    print("\n" + "=" * 70)
    print("FRESHNESS SCAN SUMMARY")
    print("=" * 70)
    print("UNIVERSE          :", len(universe))
    print("FRESH CACHE USED  :", cached_count)
    print("API REFRESHES     : 0")
    print("STALE/MISSING SKIP:", skipped_count)
    print("RESULTS           :", len(results))
    print("=" * 70)
    results.sort(key=lambda x: (x["score"], x["volume_ratio"], abs(x["change_5m"])), reverse=True)
    return results


def select_best_candidate(results, minimum_score=60):
    eligible = [x for x in results if x["score"] >= minimum_score and x["signal"] in ("BUY CE", "BUY PE") and x["volume_ratio"] >= 1.5]
    return eligible[0] if eligible else None


def print_results(results):
    print("\n" + "=" * 100)
    print("PEREZ AI — TOP HYPE CANDIDATES")
    print("=" * 100)
    for item in results[:20]:
        print(f"{item['symbol']:<14} SCORE={item['score']:>3} HYPE={item['hype_score']:>3} 5m={item['change_5m']:>6.2f}% VOL={item['volume_ratio']:>5.2f}x RSI={item['rsi']:>5.1f} BREAK={item['breakout']:<4} SIGNAL={item['signal']}")
    print("=" * 100)


if __name__ == "__main__":
    results = scan_market()
    print_results(results)
    candidate = select_best_candidate(results, 60)
    print("\nBEST CANDIDATE:")
    print(candidate if candidate else "NO HIGH-CONVICTION SETUP")
