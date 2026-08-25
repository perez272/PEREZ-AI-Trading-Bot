import time
from datetime import datetime, timedelta

from src.ai_scoring import calculate_score
from src.indicators import calculate_indicators
from src.trade_decision import get_trade_decision

from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.market_data_router import MarketDataRouter

SYMBOLS = {
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "RELIANCE": ("NSE", "2885"),
    "TCS": ("NSE", "11536"),
    "INFY": ("NSE", "1594"),
    "HDFCBANK": ("NSE", "1333"),
    "ICICIBANK": ("NSE", "4963"),
    "SBIN": ("NSE", "3045"),
    "AXISBANK": ("NSE", "5900"),
    "BHARTIARTL": ("NSE", "10604"),
}

_session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
_client = AngelClient(_session.get_client())
_router = MarketDataRouter(_client)


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
            candles, source = _router.get_candles(symbol, params, interval_minutes=5)
            if not candles:
                continue
            df = calculate_indicators(candles)
            if len(df) == 0:
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
            results.append({
                "symbol": symbol,
                "score": score,
                "close": float(last["close"]),
                "rsi": float(last["RSI"]),
                "signal": signal,
                "trend": trend,
                "data_source": source,
            })
            time.sleep(2)
        except Exception as e:
            print(f"{symbol}: {e}")

    return sorted(results, key=lambda x: x["score"], reverse=True)


def select_best_candidate(results, minimum_score=80):
    eligible = [
        x for x in results
        if x["score"] >= minimum_score and x["signal"] in ("BUY CE", "BUY PE")
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
            f" Source={item.get('data_source', 'unknown')}"
        )
    print("-" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("PEREZ AI MARKET SCANNER V2")
    print("=" * 60)
    output = scan_market()
    print_results(output)
