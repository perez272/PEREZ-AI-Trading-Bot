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

_CANDLE_CACHE = {}
_CANDLE_CACHE_MAX_AGE_SECONDS = 330


def get_client():
    global _session, _client
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
    return _client


def _parse_candle_timestamp(raw):
    timestamp = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=IST)
    return timestamp.astimezone(IST)


def _closed_candle_bucket(now=None):
    now = now or datetime.now(IST)
    minute = (now.minute // 5) * 5
    bucket = now.replace(minute=minute, second=0, microsecond=0)
    return bucket - timedelta(minutes=5)


def _validate_candle_freshness(candles, symbol):
    if not isinstance(candles, list) or not candles:
        print(f"{symbol}: NO CANDLE DATA — SKIP")
        return None
    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            print(f"{symbol}: INVALID LAST CANDLE — SKIP")
            return None

        timestamp = _parse_candle_timestamp(last[0])
        now = datetime.now(IST)
        age_seconds = (now - timestamp).total_seconds()
        if age_seconds < -60:
            print(f"{symbol}: FUTURE CANDLE — SKIP")
            return None

        if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
            expected_bucket = _closed_candle_bucket(now)
            actual_bucket = timestamp.replace(
                minute=(timestamp.minute // 5) * 5,
                second=0,
                microsecond=0,
            )
            if actual_bucket < expected_bucket:
                stale_limit_seconds = max(FRESHNESS_MAX_AGE_MINUTES * 60, 600)
                if age_seconds > stale_limit_seconds:
                    print(
                        f"{symbol}: STALE CANDLE — age={age_seconds / 60:.1f}m "
                        f"(max={stale_limit_seconds / 60:.0f}m) — SKIP"
                    )
                    return None
            elif actual_bucket > expected_bucket + timedelta(minutes=5):
                print(f"{symbol}: FUTURE/UNEXPECTED CANDLE BUCKET — SKIP")
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
    try:
        ts = _parse_candle_timestamp(candles[-1][0])
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

    current_bucket = _closed_candle_bucket(datetime.now(IST))
    entry_bucket = entry.get("bucket")
    if entry_bucket is not None and entry_bucket >= current_bucket:
        return candles
    return None


def _scan_one(symbol, exchange, token):
    candles = _cached_candles(symbol)
    freshness_age = None

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
        except Exception as exc:
            print(f"{symbol}: candle request failed — {exc}")
            return None

        if not response or not isinstance(response, dict) or not response.get("status"):
            print(f"{symbol}: candle API unavailable — SKIP")
            return None

        candles = response.get("data")
        freshness_age = _validate_candle_freshness(candles, symbol)
        if freshness_age is None:
            return None

        bucket = _candle_bucket(candles)
        if bucket is None:
            print(f"{symbol}: INVALID CANDLE BUCKET — SKIP")
            return None

        _CANDLE_CACHE[symbol] = {
            "candles": candles,
            "bucket": bucket,
            "fetched_at": time.monotonic(),
        }
    else:
        freshness_age = _validate_candle_freshness(candles, symbol)
        if freshness_age is None:
            return None

    if not isinstance(candles, list) or len(candles) < 30:
        print(f"{symbol}: Insufficient/invalid candle data — SKIP")
        return None

    try:
        df = calculate_indicators(candles)
        if df is None or df.empty or len(df) < 30:
            print(f"{symbol}: Insufficient indicator data — SKIP")
            return None

        last = df.iloc[-1]
        required = ("RSI", "EMA20", "EMA50", "close")
        if any(key not in df.columns for key in required):
            print(f"{symbol}: Missing indicator columns — SKIP")
            return None
        if any(last[key] != last[key] for key in required):
            print(f"{symbol}: Invalid indicator values — SKIP")
            return None

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
        print(f"{symbol}: indicator/scoring failure — {exc}")
        return None


def scan_market():
    results = []
    refreshed = 0
    cached = 0
    failed = 0

    for symbol, (exchange, token) in SYMBOLS.items():
        before = _CANDLE_CACHE.get(symbol, {}).get("fetched_at")
        item = _scan_one(symbol, exchange, token)
        after = _CANDLE_CACHE.get(symbol, {}).get("fetched_at")

        if after is not None and after != before:
            refreshed += 1
        elif before is not None and after == before:
            cached += 1
        else:
            failed += 1

        if item:
            results.append(item)

    print(
        f"CANDLE REQUESTS THIS SCAN: {refreshed} | "
        f"CACHE HITS: {cached} | SYMBOL SKIPS: {failed}"
    )
    return sorted(results, key=lambda x: x["score"], reverse=True)


def select_best_candidate(results, minimum_score=65):
    eligible = [
        x for x in results
        if x["score"] >= minimum_score
        and x["signal"] in ("BUY CE", "BUY PE")
        and x.get("mtf_aligned") is True
    ]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nAI Ranking")
    print("-" * 112)
    for item in results:
        print(
            f"{item['symbol']:<12} Score={item['score']}/100 "
            f"Base={item.get('base_score', '?')} Close={item['close']:.2f} "
            f"Signal={item['signal']} 15m={item.get('m15_trend', '?')} "
            f"1h={item.get('h1_trend', '?')} DataAge={item.get('candle_age_seconds', '?')}s"
        )
    print("-" * 112)


if __name__ == "__main__":
    print("=" * 72)
    print("PEREZ AI MARKET SCANNER — UPGRADED MULTI-TIMEFRAME UNIVERSE")
    print("=" * 72)
    print_results(scan_market())
