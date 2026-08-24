import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.upgrade_config import (
    SYMBOLS,
    PER_SYMBOL_DELAY_SECONDS,
    FRESHNESS_MAX_AGE_MINUTES,
)
from src.multi_timeframe import confirm as confirm_multi_timeframe
from src.market_integrity import validate_candidate

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
IST = ZoneInfo("Asia/Kolkata")
CANDLE_INTERVAL_MINUTES = 5
MAX_CANDLE_AGE_SECONDS = FRESHNESS_MAX_AGE_MINUTES * 60
HISTORICAL_LOOKBACK_DAYS = 15
_CANDLE_CACHE = {}
_SCAN_STATS = {}
_session = None
_client = None


def _reset_scan_stats():
    global _SCAN_STATS
    _SCAN_STATS = {
        "symbols": len(SYMBOLS),
        "api_attempts": 0,
        "live_refreshes": 0,
        "cache_hits": 0,
        "fresh_candles": 0,
        "fresh_to_decision_engine": 0,
        "stale_or_invalid": 0,
        "api_blocked_or_failed": 0,
        "decision_evaluations": 0,
        "results": 0,
    }


def get_scan_stats():
    return dict(_SCAN_STATS)


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


def _bucket_start(timestamp):
    return timestamp.replace(
        minute=(timestamp.minute // CANDLE_INTERVAL_MINUTES) * CANDLE_INTERVAL_MINUTES,
        second=0,
        microsecond=0,
    )


def _closed_candle_bucket(now=None):
    now = now or datetime.now(IST)
    minute = (now.minute // CANDLE_INTERVAL_MINUTES) * CANDLE_INTERVAL_MINUTES
    return now.replace(minute=minute, second=0, microsecond=0) - timedelta(minutes=CANDLE_INTERVAL_MINUTES)


def _normalize_closed_candles(candles, symbol):
    if not isinstance(candles, list) or not candles:
        return None
    valid = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts = _parse_candle_timestamp(row[0])
            values = [float(x) for x in row[1:6]]
            if any(x < 0 for x in values) or values[3] <= 0:
                continue
            valid.append((ts, list(row)))
        except (TypeError, ValueError, IndexError):
            continue
    if not valid:
        return None
    valid.sort(key=lambda item: item[0])
    now = datetime.now(IST)
    required_bucket = _closed_candle_bucket(now)
    closed = [row for ts, row in valid if _bucket_start(ts) <= required_bucket]
    if not closed:
        return None
    actual_bucket = _bucket_start(_parse_candle_timestamp(closed[-1][0]))
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE and actual_bucket != required_bucket:
        return None
    return closed


def _validate_candle_freshness(candles, symbol):
    normalized = _normalize_closed_candles(candles, symbol)
    if normalized is None:
        return None
    timestamp = _parse_candle_timestamp(normalized[-1][0])
    now = datetime.now(IST)
    age_seconds = (now - timestamp).total_seconds()
    if age_seconds < -60 or age_seconds > MAX_CANDLE_AGE_SECONDS:
        return None
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE and _bucket_start(timestamp) != _closed_candle_bucket(now):
        return None
    return age_seconds


def _candle_bucket(candles):
    try:
        return _bucket_start(_parse_candle_timestamp(candles[-1][0]))
    except (TypeError, ValueError, IndexError):
        return None


def _scan_one(symbol, exchange, token):
    candles = None
    entry = _CANDLE_CACHE.get(symbol)
    if entry and entry.get("bucket") == _closed_candle_bucket(datetime.now(IST)):
        candles = _normalize_closed_candles(entry.get("candles"), symbol)
    cache_hit = candles is not None
    if candles is None:
        _SCAN_STATS["api_attempts"] += 1
        to_date = datetime.now(IST)
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": (to_date - timedelta(days=HISTORICAL_LOOKBACK_DAYS)).strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            response = get_client().get_candles(params)
        except Exception:
            _SCAN_STATS["api_blocked_or_failed"] += 1
            return None, False
        if not isinstance(response, dict) or not response.get("status"):
            _SCAN_STATS["api_blocked_or_failed"] += 1
            return None, False
        candles = _normalize_closed_candles(response.get("data"), symbol)
        if candles is None or _validate_candle_freshness(candles, symbol) is None:
            _SCAN_STATS["stale_or_invalid"] += 1
            return None, False
        bucket = _candle_bucket(candles)
        if bucket is None:
            _SCAN_STATS["stale_or_invalid"] += 1
            return None, False
        _CANDLE_CACHE[symbol] = {"candles": candles, "bucket": bucket}
        _SCAN_STATS["live_refreshes"] += 1
    freshness_age = _validate_candle_freshness(candles, symbol)
    if freshness_age is None or len(candles) < 30:
        _SCAN_STATS["stale_or_invalid"] += 1
        return None, cache_hit
    _SCAN_STATS["fresh_candles"] += 1
    try:
        df = calculate_indicators(candles)
        if df is None or df.empty or len(df) < 30:
            return None, cache_hit
        last = df.iloc[-1]
        required = ("RSI", "EMA20", "EMA50", "close")
        if any(key not in df.columns for key in required) or any(last[key] != last[key] for key in required):
            return None, cache_hit
        _SCAN_STATS["fresh_to_decision_engine"] += 1
        base_score = calculate_score(df)
        signal, trend = get_trade_decision(
            base_score,
            float(last["RSI"]),
            float(last["EMA20"]),
            float(last["EMA50"]),
            float(last["close"]),
        )
        _SCAN_STATS["decision_evaluations"] += 1
        mtf = confirm_multi_timeframe(candles)
        score = max(0, min(100, int(base_score) + int(mtf["quality"])))
        if signal in ("BUY CE", "BUY PE") and not mtf["aligned"]:
            signal = "NO TRADE"
        candidate = {
            "symbol": symbol,
            "score": score,
            "base_score": int(base_score),
            "close": float(last["close"]),
            "rsi": float(last["RSI"]),
            "signal": signal,
            "trend": trend,
            "volume_ratio": float(last.get("volume_ratio", 0) or 0),
            "candle_age_seconds": round(freshness_age, 1),
            "candle_bucket": _candle_bucket(candles).isoformat(),
            "market_data_fresh": freshness_age <= MAX_CANDLE_AGE_SECONDS,
            "m15_trend": mtf["m15"],
            "h1_trend": mtf["h1"],
            "mtf_aligned": mtf["aligned"],
            "data_source": "Angel One live closed 5-minute candles / local MTF resample",
        }
        ok, reasons = validate_candidate(candidate)
        candidate["market_integrity_ok"] = ok
        candidate["market_integrity_reasons"] = reasons
        if not ok or not candidate["market_data_fresh"]:
            candidate["signal"] = "NO TRADE"
        if PER_SYMBOL_DELAY_SECONDS:
            time.sleep(PER_SYMBOL_DELAY_SECONDS)
        return candidate, cache_hit
    except Exception:
        return None, cache_hit


def scan_market():
    _reset_scan_stats()
    results, refreshed, cached = [], 0, 0

    # Never probe the provider when the shared circuit breaker/budget says the
    # provider is unavailable. A valid fresh cache may still be evaluated, but
    # cached data must pass exactly the same closed-candle freshness gate.
    try:
        client = get_client()
        status = client.market_data_status()
    except Exception:
        client = None
        status = None
    if status and (status["cooldown_remaining"] > 0 or status["requests_remaining"] <= 0):
        current_bucket = _closed_candle_bucket(datetime.now(IST))
        cache_available = any(
            entry.get("bucket") == current_bucket and _normalize_closed_candles(entry.get("candles"), symbol)
            for symbol, entry in _CANDLE_CACHE.items()
        )
        if not cache_available:
            _SCAN_STATS["api_blocked_or_failed"] = 1
            print(
                "MARKET DATA THROTTLED — scan deferred; "
                f"cooldown={status['cooldown_remaining']:.1f}s "
                f"budget_remaining={status['requests_remaining']}."
            )
            return []

    for symbol, (exchange, token) in SYMBOLS.items():
        item, cache_hit = _scan_one(symbol, exchange, token)
        if item:
            results.append(item)
            cached += int(cache_hit)
            refreshed += int(not cache_hit)
        elif client is not None:
            # A provider rate-limit response activates the shared circuit
            # breaker. Abort the remainder of this scan immediately rather than
            # issuing known-doomed requests for the other symbols. This is a
            # pacing fix only; it cannot bypass or relax any trade gate.
            try:
                post_status = client.market_data_status()
            except Exception:
                post_status = None
            if post_status and post_status["cooldown_remaining"] > 0:
                print(
                    "MARKET DATA CIRCUIT BREAKER — provider rate-limit detected; "
                    "aborting remainder of scan."
                )
                break
    _SCAN_STATS["cache_hits"] = cached
    _SCAN_STATS["live_refreshes"] = max(_SCAN_STATS["live_refreshes"], refreshed)
    _SCAN_STATS["results"] = len(results)
    return sorted(results, key=lambda x: x["score"], reverse=True)


def _candidate_is_fresh(candidate):
    if candidate.get("market_data_fresh") is not True or candidate.get("market_integrity_ok") is not True:
        return False
    try:
        bucket = datetime.fromisoformat(candidate["candle_bucket"])
        age = float(candidate["candle_age_seconds"])
    except (TypeError, ValueError, KeyError):
        return False
    return bucket == _closed_candle_bucket(datetime.now(IST)) and 0 <= age <= MAX_CANDLE_AGE_SECONDS


def select_best_candidate(results, minimum_score=65):
    eligible = [
        x for x in results
        if x["score"] >= minimum_score
        and x["signal"] in ("BUY CE", "BUY PE")
        and x.get("mtf_aligned") is True
        and _candidate_is_fresh(x)
    ]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nAI Ranking")
    for item in results:
        print(
            f"{item['symbol']:<12} Score={item['score']}/100 Close={item['close']:.2f} "
            f"Signal={item['signal']} MTF={item.get('m15_trend')}/{item.get('h1_trend')} "
            f"Age={item.get('candle_age_seconds')}s Fresh={item.get('market_data_fresh')} "
            f"Integrity={item.get('market_integrity_ok')}"
        )
    stats = get_scan_stats()
    print(
        "MARKET DATA QUALITY: "
        f"API={stats['api_attempts']} LiveRefresh={stats['live_refreshes']} "
        f"Cache={stats['cache_hits']} Fresh={stats['fresh_candles']} "
        f"FreshToDecision={stats['fresh_to_decision_engine']} "
        f"Decisions={stats['decision_evaluations']} "
        f"BlockedOrFailed={stats['api_blocked_or_failed']} "
        f"InvalidOrStale={stats['stale_or_invalid']}"
    )


if __name__ == "__main__":
    print_results(scan_market())
