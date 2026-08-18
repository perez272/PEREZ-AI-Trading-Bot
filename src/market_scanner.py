import time
from datetime import datetime, timedelta

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


def scan_market():
    results = []
    to_date = datetime.now()
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
                continue
            if not response.get("status"):
                print(f"{symbol}: API returned status=False")
                continue
            if not response.get("data"):
                print(f"{symbol}: No candle data")
                continue

            df = calculate_indicators(response["data"])
            if df.empty or len(df) < 30:
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
