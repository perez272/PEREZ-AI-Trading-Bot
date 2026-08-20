import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.indicators import calculate_indicators
from src.pro_engine import evaluate
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.upgrade_config import SYMBOLS, FRESHNESS_MAX_AGE_MINUTES, PER_SYMBOL_DELAY_SECONDS, MAX_WORKERS

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
        print(f"{symbol}: NO CANDLE DATA")
        return False
    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            print(f"{symbol}: INVALID LAST CANDLE")
            return False
        timestamp = datetime.fromisoformat(str(last[0]).strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        timestamp = timestamp.astimezone(IST)
        now = datetime.now(IST)
        age_seconds = (now - timestamp).total_seconds()
        if age_seconds < -60:
            print(f"{symbol}: FUTURE CANDLE — SKIP")
            return False
        if MARKET_OPEN <= now.time() <= MARKET_CLOSE and age_seconds > FRESHNESS_MAX_AGE_MINUTES * 60:
            print(f"{symbol}: STALE CANDLE — age={age_seconds / 60:.1f}m — SKIP")
            return False
        for value in last[1:6]:
            if float(value) < 0:
                print(f"{symbol}: INVALID CANDLE VALUE — SKIP")
                return False
        if float(last[4]) <= 0:
            print(f"{symbol}: INVALID CLOSE — SKIP")
            return False
        return True
    except (TypeError, ValueError, IndexError) as exc:
        print(f"{symbol}: INVALID CANDLE TIMESTAMP/DATA — {exc}")
        return False


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
    try:
        response = get_client().get_candles(params)
        if not response or not response.get("status"):
            return None
        candles = response.get("data")
        if not _validate_candle_freshness(candles, symbol):
            return None
        df = calculate_indicators(candles)
        if df.empty or len(df) < 30:
            return None
        decision = evaluate(df)
        last = df.iloc[-1]
        if PER_SYMBOL_DELAY_SECONDS:
            time.sleep(PER_SYMBOL_DELAY_SECONDS)
        return {
            "symbol": symbol,
            "score": decision["score"],
            "close": float(last["close"]),
            "rsi": float(last["RSI"]),
            "signal": decision["direction"],
            "trend": decision["regime"],
            "volume_ratio": decision["volume_ratio"],
            "structure": decision["structure"],
            "reasons": decision["reasons"],
        }
    except Exception as exc:
        print(f"{symbol}: {exc}")
        return None


def scan_market():
    """Fast parallel first-pass scan; weak/invalid symbols are discarded."""
    results = []
    workers = max(1, min(int(MAX_WORKERS), len(SYMBOLS)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_scan_one, symbol, exchange, token) for symbol, (exchange, token) in SYMBOLS.items()]
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)
    return sorted(results, key=lambda x: x["score"], reverse=True)


def select_best_candidate(results, minimum_score=65):
    eligible = [x for x in results if x["score"] >= minimum_score and x["signal"] in ("BUY CE", "BUY PE")]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nPEREZ PRO AI — OPPORTUNITY RANKING")
    print("-" * 100)
    for rank, item in enumerate(results, 1):
        print(
            f"#{rank:<2} {item['symbol']:<12} Score={item['score']:>5.1f} "
            f"Signal={item['signal']:<8} Regime={item['trend']:<18} "
            f"Structure={item['structure']:<18} Vol={item['volume_ratio']:.2f}x"
        )
    print("-" * 100)


if __name__ == "__main__":
    print("=" * 100)
    print("PEREZ AI PRO MARKET SCANNER — FAST MULTI-FACTOR ENGINE")
    print("=" * 100)
    print_results(scan_market())
