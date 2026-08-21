import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.upgrade_config import SYMBOLS, FRESHNESS_MAX_AGE_MINUTES, PER_SYMBOL_DELAY_SECONDS
from src.multi_timeframe import confirm as confirm_multi_timeframe

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
IST = ZoneInfo("Asia/Kolkata")
_session = None
_client = None

# Historical candles are reused for the current 5-minute candle bucket.
# This prevents the 60-second main loop from downloading the same 5-day
# history repeatedly. A refresh is needed only when the candle bucket changes
# or when cached data fails freshness validation.
_CANDLE_CACHE = {}
_CANDLE_CACHE_MAX_AGE_SECONDS = 330


def get_client():
    global _session, _client
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
    return _client


def _validate_candle_freshness(candles, symbol):
    if not isinstance(candles, list) or not candles:
        print(f"{symbol}: NO CANDLE DATA")
        return None
    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            print(f"{symbol}: INVALID LAST CANDLE")
            return None
        timestamp = datetime.fromisoformat(str(last[0]).strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        timestamp = timestamp.astimezone(IST)
        now = datetime.now(IST)
        age_seconds = (now - timestamp).total_seconds()
        if age_seconds < -60:
            print(f"{symbol}: FUTURE CANDLE — SKIP")
            return None
        if MARKET_OPEN <= now.time() <= MARKET_CLOSE and age_seconds > FRESHNESS_MAX_AGE_MINUTES * 60:
            print(f"{symbol}: STALE CANDLE — age={age_seconds / 60:.1f}m (max={FRESHNESS_MAX_AGE_MINUTES}m) — SKIP")
            return None
        for value in last[1:6]:
            if float(value) < 0:
                print(f"{symbol}: INVALID CANDLE VALUE — SKIP")
                return None
        if float(last[4]) <= 0:
            print(f"{symbol}: INVALID CLOSE — SKIP")
            return None
        return age_seconds
    except (TypeError, ValueError, IndexError) as exc:
        print(f"{symbol}: INVALID CANDLE TIMESTAMP/DATA — {exc}")
        return None


def _candle_bucket(candles):
    """Return the 5-minute bucket of the latest candle timestamp."""
    try:
        raw = str(candles[-1][0]).strip().replace("Z", "+00:00")
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        ts = ts.astimezone(IST)
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
    except (TypeError, ValueError, IndexError):
        return None


def _cached_candles(symbol):
    entry = _CANDLE_CACHE.get(symbol)
    if not entry:
        return None
    if time.monotonic() - entry["fetched_at"] > _CANDLE_CACHE_MAX_AGE_SECONDS:
        _CANDLE_CACHE.pop(symbol, None)
        return None
    candles = entry.get("candles")
    if _validate_candle_freshness(candles, symbol) is None:
        _CANDLE_CACHE.pop(symbol, None)
        return None
    # Reuse only while the market is still in the same 5-minute candle bucket.
    # Outside market hours this still safely avoids unnecessary requests.
    current_bucket = datetime.now(IST).replace(
        minute=(datetime.now(IST).minute // 5) * 5,
        second=0,
        microsecond=0,
    )
    if entry.get("bucket") != current_bucket:
        return None
    return candles


def _scan_one(symbol, exchange, token):
    candles = _cached_candles(symbol)
    if candles is None:
        to_date = datetime.now(IST)
        from_date = to_date - timedelta(days=5)
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            response = get_client().get_candles(params)
            if not response or not response.get("status"):
                print(f"{symbol}: API returned no valid data")
                return None
            candles = response.get("data")
            freshness_age = _validate_candle_freshness(candles, symbol)
            if freshness_age is None:
                return None
            bucket = _candle_bucket(candles)
            _CANDLE_CACHE[symbol] = {
                "candles": candles,
                "bucket": bucket,
                "fetched_at": time.monotonic(),
            }
        except Exception as exc:
            print(f"{symbol}: {exc}")
            return None
    else:
        freshness_age = _validate_candle_freshness(candles, symbol)
        if freshness_age is None:
            return None

    try:
        df = calculate_indicators(candles)
        if df.empty or len(df) < 30:
            print(f"{symbol}: Insufficient indicator data")
            return None
        last = df.iloc[-1]
        base_score = calculate_score(df)
        signal, trend = get_trade_decision(
            base_score,
            float(last["RSI"]),
            float(last["EMA20"]),
            float(last["EMA50"]),
            float(last["close"]),
        )
        mtf = confirm_multi_timeframe(candles)
        score = max(0, min(100, int(base_score) + int(mtf["quality"])))
        if signal in ("BUY CE", "BUY PE") and not mtf["aligned"]:
            signal = "NO TRADE"
        if PER_SYMBOL_DELAY_SECONDS:
            time.sleep(PER_SYMBOL_DELAY_SECONDS)
        return {
            "symbol": symbol,
            "score": score,
            "base_score": int(base_score),
            "close": float(last["close"]),
            "rsi": float(last["RSI"]),
            "signal": signal,
            "trend": trend,
            "volume_ratio": float(last.get("volume_ratio", 0) or 0),
            "candle_age_seconds": round(freshness_age, 1),
            "m15_trend": mtf["m15"],
            "h1_trend": mtf["h1"],
            "mtf_aligned": mtf["aligned"],
            "data_source": "Angel One live candles / local MTF resample",
        }
    except Exception as exc:
        print(f"{symbol}: {exc}")
        return None


def scan_market():
    results = []
    # Keep broker requests serialized. Cached scans perform zero broker candle
    # requests until the 5-minute candle bucket changes.
    refreshed = 0
    cached = 0
    for symbol, (exchange, token) in SYMBOLS.items():
        before = _CANDLE_CACHE.get(symbol, {}).get("fetched_at")
        item = _scan_one(symbol, exchange, token)
        after = _CANDLE_CACHE.get(symbol, {}).get("fetched_at")
        if after is not None and after != before:
            refreshed += 1
        elif before is not None and after == before:
            cached += 1
        if item:
            results.append(item)
    print(f"CANDLE REQUESTS THIS SCAN: {refreshed} | CACHE HITS: {cached}")
    return sorted(results, key=lambda x: x["score"], reverse=True)


def select_best_candidate(results, minimum_score=65):
    eligible = [x for x in results if x["score"] >= minimum_score and x["signal"] in ("BUY CE", "BUY PE") and x.get("mtf_aligned") is True]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nAI Ranking")
    print("-" * 112)
    for item in results:
        print(f"{item['symbol']:<12} Score={item['score']}/100 Base={item.get('base_score', '?')} Close={item['close']:.2f} Signal={item['signal']} 15m={item.get('m15_trend', '?')} 1h={item.get('h1_trend', '?')} DataAge={item.get('candle_age_seconds', '?')}s")
    print("-" * 112)


if __name__ == "__main__":
    print("=" * 72)
    print("PEREZ AI MARKET SCANNER — UPGRADED MULTI-TIMEFRAME UNIVERSE")
    print("=" * 72)
    print_results(scan_market())
