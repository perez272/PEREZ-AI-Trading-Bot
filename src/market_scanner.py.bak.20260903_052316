import json
import os
import tempfile
import time
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.market_data_router import MarketDataRouter
from src.upgrade_config import FRESHNESS_MAX_AGE_MINUTES, PER_SYMBOL_DELAY_SECONDS
from src.scanner_universe import build_scan_symbols
from src.multi_timeframe import confirm as confirm_multi_timeframe
from src.market_integrity import validate_candidate

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
IST = ZoneInfo("Asia/Kolkata")
CANDLE_INTERVAL_MINUTES = 5
MAX_CANDLE_AGE_SECONDS = FRESHNESS_MAX_AGE_MINUTES * 60
HISTORICAL_LOOKBACK_DAYS = 15
CANDLE_CACHE_FILE = Path(os.getenv("PEREZ_CANDLE_CACHE_FILE", "/tmp/perez_ai_candle_cache.json"))
_CANDLE_CACHE = {}
_SCAN_STATS = {}
_session = None
_client = None
_router = None


def _load_candle_cache():
    """Load the last validated candle set so service restarts do not burst the API.

    Cache entries are still subjected to the normal closed-candle and freshness
    gates before they can reach indicators or the decision engine. A corrupt or
    incompatible cache is discarded rather than trusted.
    """
    try:
        raw = json.loads(CANDLE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        result = {}
        for symbol, entry in raw.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("candles"), list):
                continue
            bucket_raw = entry.get("bucket")
            try:
                bucket = datetime.fromisoformat(str(bucket_raw))
            except (TypeError, ValueError):
                continue
            result[str(symbol)] = {
                "candles": entry["candles"],
                "bucket": bucket,
                "source": str(entry.get("source") or "cache"),
            }
        return result
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def _persist_candle_cache():
    """Atomically persist only validated scanner candles; never block on cache failure."""
    payload = {}
    for symbol, entry in _CANDLE_CACHE.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("candles"), list):
            continue
        bucket = entry.get("bucket")
        if not isinstance(bucket, datetime):
            continue
        payload[symbol] = {
            "candles": entry["candles"],
            "bucket": bucket.isoformat(),
            "source": entry.get("source", "cache"),
        }
    try:
        CANDLE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="perez-candle-cache-", dir=str(CANDLE_CACHE_FILE.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, CANDLE_CACHE_FILE)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    except (OSError, TypeError, ValueError) as exc:
        print(f"[MARKET DATA] Persistent candle cache write skipped: {exc}")


_CANDLE_CACHE.update(_load_candle_cache())


def _reset_scan_stats(symbol_count):
    global _SCAN_STATS
    _SCAN_STATS = {
        "symbols": symbol_count, "api_attempts": 0, "live_refreshes": 0,
        "cache_hits": 0, "fresh_candles": 0, "fresh_to_decision_engine": 0,
        "stale_or_invalid": 0, "api_blocked_or_failed": 0, "decision_evaluations": 0,
        "results": 0, "upstox_fallback_attempts": 0, "upstox_fallback_successes": 0,
    }


def get_scan_stats():
    return dict(_SCAN_STATS)


def get_scan_telemetry():
    """Compatibility API for diagnostics and runtime telemetry consumers.

    The scanner's canonical telemetry store is _SCAN_STATS and is exposed
    through get_scan_stats(). Keep this alias read-only so telemetry consumers
    cannot mutate scanner state or affect trading decisions.
    """
    return get_scan_stats()


def get_client():
    global _session, _client, _router
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
        _router = MarketDataRouter(_client)
    return _client


def _get_router():
    get_client()
    return _router


def _parse_candle_timestamp(raw):
    timestamp = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=IST)
    return timestamp.astimezone(IST)


def _bucket_start(timestamp):
    return timestamp.replace(minute=(timestamp.minute // CANDLE_INTERVAL_MINUTES) * CANDLE_INTERVAL_MINUTES, second=0, microsecond=0)


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

    # During the live session, require the latest closed 5-minute candle.
    # After market close, do NOT compare the final market candle against the
    # wall clock. The exchange is closed, so no newer candle can legitimately
    # exist. Validate freshness against the market close boundary instead.
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
        required_bucket = _closed_candle_bucket(now)
        if _bucket_start(timestamp) != required_bucket:
            return None
        candle_close = _bucket_start(timestamp) + timedelta(minutes=CANDLE_INTERVAL_MINUTES)
        age_seconds = max(0.0, (now - candle_close).total_seconds())
        if age_seconds > MAX_CANDLE_AGE_SECONDS:
            return None
        return age_seconds

    if now.time() > MARKET_CLOSE:
        market_close_dt = now.replace(
            hour=MARKET_CLOSE.hour,
            minute=MARKET_CLOSE.minute,
            second=0,
            microsecond=0,
        )
        candle_close = _bucket_start(timestamp) + timedelta(minutes=CANDLE_INTERVAL_MINUTES)

        # Only the final valid market-session candle is accepted after close.
        if candle_close.time() > MARKET_CLOSE:
            return None

        age_seconds = max(0.0, (market_close_dt - candle_close).total_seconds())
        if age_seconds > MAX_CANDLE_AGE_SECONDS:
            # The data itself is valid, but the market session is too far past
            # the final candle for a trading decision.
            return None
        return age_seconds

    return None


def _candle_bucket(candles):
    try:
        return _bucket_start(_parse_candle_timestamp(candles[-1][0]))
    except (TypeError, ValueError, IndexError):
        return None


def _historical_params(exchange, token):
    to_date = datetime.now(IST)
    return {
        "exchange": exchange, "symboltoken": token, "interval": "FIVE_MINUTE",
        "fromdate": (to_date - timedelta(days=HISTORICAL_LOOKBACK_DAYS)).strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }


def _safe_pct(numerator, denominator):
    try:
        denominator = float(denominator)
        return float(numerator) / denominator * 100.0 if denominator else 0.0
    except (TypeError, ValueError):
        return 0.0


def _derive_momentum_fields(df):
    """Derive early-move features so the momentum layer is not blind to breakouts."""
    last = df.iloc[-1]
    previous = df.iloc[-2] if len(df) >= 2 else last
    lookback = df.iloc[-13:-1] if len(df) >= 13 else df.iloc[:-1]
    prior_high = float(lookback["high"].max()) if not lookback.empty else float(last["high"])
    prior_low = float(lookback["low"].min()) if not lookback.empty else float(last["low"])
    close = float(last["close"])
    candle_range = max(float(last["high"]) - float(last["low"]), 1e-9)
    body = abs(float(last["close"]) - float(last["open"]))
    direction_breakout = max(
        _safe_pct(close - prior_high, prior_high),
        _safe_pct(prior_low - close, prior_low),
        0.0,
    )
    volume_ratio = 0.0
    if len(df) >= 21:
        avg_volume = float(df["volume"].iloc[-21:-1].mean())
        volume_ratio = float(last.get("volume", 0) or 0) / avg_volume if avg_volume > 0 else 0.0
    rsi_slope = float(last.get("RSI", 0) or 0) - float(previous.get("RSI", 0) or 0)
    atr = float(last.get("ATR", 0) or 0)
    atr_pct = _safe_pct(atr, close)
    ema_gap_pct = abs(_safe_pct(float(last.get("EMA20", close)) - float(last.get("EMA50", close)), close))
    return {
        "breakout_strength": round(direction_breakout, 4),
        "body_strength": round(body / candle_range, 4),
        "ema_gap_pct": round(ema_gap_pct, 4),
        "rsi_slope": round(rsi_slope, 4),
        "atr_pct": round(atr_pct, 4),
        "percent_change": round(_safe_pct(close - float(previous.get("close", close)), float(previous.get("close", close))), 4),
        "volume_ratio": round(volume_ratio, 4),
    }


def _scan_one(symbol, exchange, token):
    candles = None
    upstox_snapshot = None
    source = "cache"
    entry = _CANDLE_CACHE.get(symbol)
    if entry and entry.get("bucket") == _closed_candle_bucket(datetime.now(IST)):
        candles = _normalize_closed_candles(entry.get("candles"), symbol)
    cache_hit = candles is not None
    if candles is None:
        _SCAN_STATS["api_attempts"] += 1
        try:
            router = _get_router()
            candles, source = router.get_candles(
                symbol,
                _historical_params(exchange, token),
                CANDLE_INTERVAL_MINUTES,
            )
            upstox_snapshot = router.get_validation_snapshot(symbol)
        except Exception as exc:
            _SCAN_STATS["api_blocked_or_failed"] += 1
            print(f"[MARKET DATA] Provider routing failed for {symbol}: {exc}")
            return None, False
        if source == "upstox":
            _SCAN_STATS["upstox_fallback_attempts"] += 1
            _SCAN_STATS["upstox_fallback_successes"] += int(bool(candles))
        if not candles:
            _SCAN_STATS["api_blocked_or_failed"] += 1
            return None, False
        candles = _normalize_closed_candles(candles, symbol)
        if candles is None or _validate_candle_freshness(candles, symbol) is None:
            _SCAN_STATS["stale_or_invalid"] += 1
            return None, False
        bucket = _candle_bucket(candles)
        if bucket is None:
            _SCAN_STATS["stale_or_invalid"] += 1
            return None, False
        _CANDLE_CACHE[symbol] = {
            "candles": candles,
            "bucket": bucket,
            "source": source,
            "upstox_snapshot": upstox_snapshot,
        }
        _persist_candle_cache()
        _SCAN_STATS["live_refreshes"] += 1
    else:
        source = entry.get("source", "cache") if entry else "cache"
        upstox_snapshot = entry.get("upstox_snapshot") if entry else None
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
        signal, trend = get_trade_decision(base_score, float(last["RSI"]), float(last["EMA20"]), float(last["EMA50"]), float(last["close"]))
        _SCAN_STATS["decision_evaluations"] += 1
        mtf = confirm_multi_timeframe(candles)
        score = max(0, min(100, int(base_score) + int(mtf["quality"])))
        fields = _derive_momentum_fields(df)
        if signal in ("BUY CE", "BUY PE") and not mtf["aligned"]:
            signal = "NO TRADE"
        candidate = {
            "symbol": symbol, "score": score, "base_score": int(base_score), "close": float(last["close"]),
            "rsi": float(last["RSI"]), "signal": signal, "trend": trend,
            **fields,
            "candle_age_seconds": round(freshness_age, 1),
            "candle_bucket": _candle_bucket(candles).isoformat(), "market_data_fresh": freshness_age <= MAX_CANDLE_AGE_SECONDS,
            "m15_trend": mtf["m15"], "h1_trend": mtf["h1"], "mtf_aligned": mtf["aligned"],
            "data_source": source,
            "upstox_snapshot": upstox_snapshot,
        }
        ok, reasons = validate_candidate(candidate)
        candidate["market_integrity_ok"] = ok
        candidate["market_integrity_reasons"] = reasons
        if not ok or not candidate["market_data_fresh"]:
            candidate["signal"] = "NO TRADE"
        if PER_SYMBOL_DELAY_SECONDS:
            time.sleep(PER_SYMBOL_DELAY_SECONDS)
        return candidate, cache_hit
    except Exception as exc:
        print(f"[MARKET DATA] Decision pipeline failed for {symbol}: {exc}")
        return None, cache_hit


def scan_market():
    symbols = build_scan_symbols()
    _reset_scan_stats(len(symbols))
    results, refreshed, cached = [], 0, 0
    for symbol, (exchange, token) in symbols.items():
        item, cache_hit = _scan_one(symbol, exchange, token)
        if item:
            results.append(item)
            cached += int(cache_hit)
            refreshed += int(not cache_hit)
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
            f"Breakout={item.get('breakout_strength', 0):.2f}% Vol={item.get('volume_ratio', 0):.2f}x "
            f"Integrity={item.get('market_integrity_ok')} Source={item.get('data_source')}"
        )
    stats = get_scan_stats()
    print(
        "MARKET DATA QUALITY: "
        + f"Universe={stats['symbols']} API={stats['api_attempts']} LiveRefresh={stats['live_refreshes']} "
        + f"Cache={stats['cache_hits']} Fresh={stats['fresh_candles']} FreshToDecision={stats['fresh_to_decision_engine']} "
        + f"Decisions={stats['decision_evaluations']} BlockedOrFailed={stats['api_blocked_or_failed']} "
        + f"InvalidOrStale={stats['stale_or_invalid']} UpstoxFallback={stats['upstox_fallback_successes']}/{stats['upstox_fallback_attempts']}"
    )


if __name__ == "__main__":
    print_results(scan_market())
