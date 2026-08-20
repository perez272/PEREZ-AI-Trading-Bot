import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.optionable_universe import get_optionable_universe
from src.upgrade_config import (
    SYMBOLS,
    FRESHNESS_MAX_AGE_MINUTES,
    PER_SYMBOL_DELAY_SECONDS,
    MAX_WORKERS,
    MAX_SCAN_SYMBOLS,
    UNIVERSE_REQUIRE_FNO,
)

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
IST = ZoneInfo("Asia/Kolkata")
_session = None
_client = None


def get_client():
    global _session, _client
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
    return _client


def _validate_candle_freshness(candles, symbol):
    if not isinstance(candles, list) or not candles:
        print(f"SCAN {symbol} | status=NO_DATA")
        return False, None
    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            print(f"SCAN {symbol} | status=INVALID_CANDLE")
            return False, None
        timestamp = datetime.fromisoformat(str(last[0]).strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        timestamp = timestamp.astimezone(IST)
        now = datetime.now(IST)
        age_seconds = (now - timestamp).total_seconds()
        age_minutes = age_seconds / 60.0
        if age_seconds < -60:
            print(f"SCAN {symbol} | status=FUTURE_CANDLE | age={age_minutes:.2f}m")
            return False, age_minutes
        if MARKET_OPEN <= now.time() <= MARKET_CLOSE and age_seconds > FRESHNESS_MAX_AGE_MINUTES * 60:
            print(f"SCAN {symbol} | status=STALE | age={age_minutes:.2f}m | max={FRESHNESS_MAX_AGE_MINUTES}m")
            return False, age_minutes
        for value in last[1:6]:
            if float(value) < 0:
                print(f"SCAN {symbol} | status=INVALID_VALUE")
                return False, age_minutes
        if float(last[4]) <= 0:
            print(f"SCAN {symbol} | status=INVALID_CLOSE")
            return False, age_minutes
        return True, age_minutes
    except (TypeError, ValueError, IndexError) as exc:
        print(f"SCAN {symbol} | status=INVALID_TIMESTAMP | error={exc}")
        return False, None


def _dynamic_symbols():
    """Build a bounded F&O-underlying universe and retain major index coverage."""
    universe = get_optionable_universe() if UNIVERSE_REQUIRE_FNO else {}
    if not universe:
        return dict(SYMBOLS)

    # Always retain the configured index/large-cap symbols first, then add
    # additional F&O underlyings from the local Angel One master. This avoids
    # losing NIFTY/BANKNIFTY/FINNIFTY when the dynamic equity universe loads.
    selected = dict(SYMBOLS)
    remaining = [
        (name, item)
        for name, item in sorted(universe.items(), key=lambda pair: pair[0])
        if name not in selected
    ]
    capacity = max(0, MAX_SCAN_SYMBOLS - len(selected))
    for name, item in remaining[:capacity]:
        token = item.get("token")
        exchange = item.get("exchange", "NSE")
        if token:
            selected[name] = (str(exchange), str(token))
    return selected


def _scan_one(symbol, exchange, token):
    to_date = datetime.now(IST)
    from_date = to_date - timedelta(days=5)
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }
    started = time.monotonic()
    try:
        response = get_client().get_candles(params)
        if not response or not response.get("status"):
            return {"symbol": symbol, "status": "API_NO_DATA", "latency_ms": int((time.monotonic() - started) * 1000)}
        candles = response.get("data")
        fresh, age_minutes = _validate_candle_freshness(candles, symbol)
        if not fresh:
            return {"symbol": symbol, "status": "STALE_OR_INVALID", "age_minutes": age_minutes, "latency_ms": int((time.monotonic() - started) * 1000)}
        df = calculate_indicators(candles)
        if df.empty or len(df) < 30:
            return {"symbol": symbol, "status": "INSUFFICIENT_DATA", "age_minutes": age_minutes, "latency_ms": int((time.monotonic() - started) * 1000)}
        last = df.iloc[-1]
        score = int(calculate_score(df))
        signal, trend = get_trade_decision(
            score,
            float(last["RSI"]),
            float(last["EMA20"]),
            float(last["EMA50"]),
            float(last["close"]),
        )
        item = {
            "symbol": symbol,
            "status": "OK",
            "age_minutes": age_minutes,
            "score": score,
            "close": float(last["close"]),
            "rsi": float(last["RSI"]),
            "signal": signal,
            "trend": trend,
            "volume_ratio": float(last.get("volume_ratio", 0) or 0),
            "candles": len(df),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        if PER_SYMBOL_DELAY_SECONDS:
            time.sleep(PER_SYMBOL_DELAY_SECONDS)
        return item
    except Exception as exc:
        return {"symbol": symbol, "status": "ERROR", "error": str(exc), "latency_ms": int((time.monotonic() - started) * 1000)}


def scan_market():
    symbols = _dynamic_symbols()
    started = time.monotonic()
    print("\nPEREZ AI SCAN TELEMETRY")
    print("=" * 92)
    print(f"SCAN_START={datetime.now(IST).isoformat(timespec='seconds')} | UNIVERSE={len(symbols)} | MAX_WORKERS={MAX_WORKERS} | PAPER_ONLY=YES")
    results = []
    counts = {"OK": 0, "STALE_OR_INVALID": 0, "API_NO_DATA": 0, "INSUFFICIENT_DATA": 0, "ERROR": 0}
    with ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS)) as pool:
        futures = {pool.submit(_scan_one, symbol, exchange, token): symbol for symbol, (exchange, token) in symbols.items()}
        for future in as_completed(futures):
            item = future.result()
            status = item.get("status", "ERROR")
            counts[status] = counts.get(status, 0) + 1
            if status == "OK":
                results.append(item)
                print(
                    f"SCAN {item['symbol']:<14} status=FRESH age={item['age_minutes']:.2f}m "
                    f"close={item['close']:.2f} RSI={item['rsi']:.1f} score={item['score']:>3} "
                    f"signal={item['signal']:<7} trend={item['trend']:<8} candles={item['candles']} latency={item['latency_ms']}ms"
                )
            else:
                extra = f" age={item['age_minutes']:.2f}m" if item.get("age_minutes") is not None else ""
                print(f"SCAN {item['symbol']:<14} status={status}{extra}")
    elapsed = time.monotonic() - started
    results.sort(key=lambda x: x["score"], reverse=True)
    print("-" * 92)
    print(
        "SCAN_SUMMARY "
        f"universe={len(symbols)} fresh={counts.get('OK', 0)} "
        f"stale_invalid={counts.get('STALE_OR_INVALID', 0)} "
        f"api_no_data={counts.get('API_NO_DATA', 0)} "
        f"insufficient={counts.get('INSUFFICIENT_DATA', 0)} "
        f"errors={counts.get('ERROR', 0)} results={len(results)} elapsed={elapsed:.1f}s"
    )
    print("TOP_CANDIDATES")
    for item in results[:10]:
        print(
            f"TOP {item['symbol']:<14} score={item['score']:>3} close={item['close']:.2f} "
            f"RSI={item['rsi']:.1f} signal={item['signal']} trend={item['trend']} age={item['age_minutes']:.2f}m"
        )
    print("=" * 92)
    return results


def select_best_candidate(results, minimum_score=65):
    eligible = [x for x in results if x["score"] >= minimum_score and x["signal"] in ("BUY CE", "BUY PE")]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nAI Ranking")
    print("-" * 92)
    for item in results:
        print(
            f"{item['symbol']:<14} Score={item['score']:>3}/100 Close={item['close']:.2f} "
            f"RSI={item['rsi']:.1f} Signal={item['signal']:<7} Trend={item['trend']:<8} Age={item['age_minutes']:.2f}m"
        )
    print("-" * 92)


if __name__ == "__main__":
    print_results(scan_market())
