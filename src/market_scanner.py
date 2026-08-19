import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient

SYMBOLS = {
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "ICICIBANK": ("NSE", "4963"),
}

FRESHNESS_MAX_AGE_MINUTES = 10
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
IST = ZoneInfo("Asia/Kolkata")

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
        _client = AngelClient(_session.get_client())

    return _client


def _validate_candle_freshness(candles, symbol):
    """Fail closed on malformed, future-dated, or stale Angel One candles."""
    if not isinstance(candles, list) or not candles:
        print(f"{symbol}: NO CANDLE DATA")
        return False

    try:
        last = candles[-1]
        if not isinstance(last, (list, tuple)) or len(last) < 6:
            print(f"{symbol}: INVALID LAST CANDLE")
            return False

        raw_timestamp = str(last[0]).strip().replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(raw_timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=IST)
        timestamp = timestamp.astimezone(IST)

        now = datetime.now(IST)
        age_seconds = (now - timestamp).total_seconds()

        if age_seconds < -60:
            print(f"{symbol}: FUTURE CANDLE — SKIP")
            return False

        if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
            max_age_seconds = FRESHNESS_MAX_AGE_MINUTES * 60
            if age_seconds > max_age_seconds:
                print(
                    f"{symbol}: STALE CANDLE — age={age_seconds / 60:.1f}m "
                    f"(max={FRESHNESS_MAX_AGE_MINUTES}m) — SKIP"
                )
                return False

        for value in last[1:6]:
            if float(value) < 0:
                print(f"{symbol}: INVALID CANDLE VALUE — SKIP")
                return False

        if float(last[4]) <= 0:
            print(f"{symbol}: INVALID CLOSE — SKIP")
            return False

        print(f"{symbol}: FRESH CANDLE — age={max(0.0, age_seconds) / 60:.1f}m")
        return True
    except (TypeError, ValueError, IndexError) as exc:
        print(f"{symbol}: INVALID CANDLE TIMESTAMP/DATA — {exc}")
        return False


def scan_market():
    results = []
    to_date = datetime.now(IST)
    from_date = to_date - timedelta(days=5)

    for symbol, (exchange, token) in SYMBOLS.items():
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        try:
            response = get_client().get_candles(params)

            if not response:
                print(f"{symbol}: Empty API response")
                continue
            if not response.get("status"):
                print(f"{symbol}: API returned status=False")
                continue
            if not _validate_candle_freshness(response.get("data"), symbol):
                continue

            df = calculate_indicators(response["data"])
            if df.empty or len(df) < 30:
                print(f"{symbol}: Insufficient indicator data")
                continue

            last = df.iloc[-1]
            score = calculate_score(df)

            signal, trend = get_trade_decision(
                score,
                float(last["RSI"]),
                float(last["EMA20"]),
                float(last["EMA50"]),
                float(last["close"]),
            )

            results.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "close": float(last["close"]),
                    "rsi": float(last["RSI"]),
                    "signal": signal,
                    "trend": trend,
                }
            )

            time.sleep(2)

        except Exception as exc:
            print(f"{symbol}: {exc}")

    return sorted(results, key=lambda x: x["score"], reverse=True)


def select_best_candidate(results, minimum_score=80):
    eligible = [
        x
        for x in results
        if x["score"] >= minimum_score
        and x["signal"] in ("BUY CE", "BUY PE")
    ]
    return eligible[0] if eligible else None


def print_results(results):
    print("\nAI Ranking")
    print("-" * 60)
    for item in results:
        print(
            f"{item['symbol']:<12}"
            f" Score={item['score']}/100"
            f" Close={item['close']:.2f}"
            f" Signal={item['signal']}"
        )
    print("-" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("PEREZ AI MARKET SCANNER V2")
    print("=" * 60)
    print_results(scan_market())
