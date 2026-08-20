"""PRO scanner: parallel symbols, sequential frames, strict admission gates."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from src.broker.angel_client import AngelClient
from src.broker.session_manager import SessionManager
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
from src.indicators import calculate_indicators
from src.pro_engine import evaluate_multi_timeframe
from src.upgrade_config import MAX_WORKERS, PER_SYMBOL_DELAY_SECONDS, SYMBOLS

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
TIMEFRAMES = {
    "5m": ("FIVE_MINUTE", 5, 5, 7),
    "15m": ("FIFTEEN_MINUTE", 15, 15, 20),
    "60m": ("ONE_HOUR", 60, 60, 75),
}
_session = None
_client = None


def _client_instance():
    global _session, _client
    if _client is None:
        _session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
        _client = AngelClient(_session.get_client(), session_manager=_session)
    return _client


def _closed_candles(raw, symbol, minutes, max_age):
    if not isinstance(raw, list) or len(raw) < 30:
        return None
    now = datetime.now(IST)
    clean = []
    try:
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                return None
            ts = datetime.fromisoformat(str(row[0]).strip().replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            ts = ts.astimezone(IST)
            op, high, low, close, volume = [float(x) for x in row[1:6]]
            if ts > now + timedelta(seconds=60):
                return None
            if min(op, high, low, close) <= 0 or volume < 0:
                return None
            if high < max(op, close) or low > min(op, close) or high < low:
                return None
            clean.append([ts, op, high, low, close, volume])
        closed = [r for r in clean if r[0] + timedelta(minutes=minutes) <= now]
        closed.sort(key=lambda r: r[0])
        if len(closed) < 30:
            return None
        age = (now - closed[-1][0]).total_seconds() / 60
        if MARKET_OPEN <= now.time() <= MARKET_CLOSE and age > max_age:
            print(f"{symbol}: stale {minutes}m data ({age:.1f}m)")
            return None
        return closed
    except (TypeError, ValueError, IndexError):
        return None


def _fetch(symbol, exchange, token, tf):
    interval, minutes, days, max_age = TIMEFRAMES[tf]
    now = datetime.now(IST)
    response = _client_instance().get_candles({
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M"),
        "todate": now.strftime("%Y-%m-%d %H:%M"),
    })
    if not response or not response.get("status"):
        return None
    candles = _closed_candles(response.get("data"), symbol, minutes, max_age)
    return calculate_indicators(candles) if candles else None


def _scan_one(symbol, exchange, token):
    try:
        # Keep only symbols concurrent. The three frames for one symbol are
        # fetched sequentially to avoid multiplying broker API concurrency.
        frames = {tf: _fetch(symbol, exchange, token, tf) for tf in TIMEFRAMES}
        if any(frame is None for frame in frames.values()):
            return None
        decision = evaluate_multi_timeframe(frames)
        if decision.get("decision") != "ADMIT":
            return None
        last = frames["5m"].iloc[-1]
        tfs = decision["timeframes"]
        return {
            "symbol": symbol,
            "score": decision["score"],
            "signal": decision["direction"],
            "close": float(last["close"]),
            "rsi": float(last["RSI"]),
            "atr": float(last["ATR"]),
            "vwap": float(last["VWAP"]),
            "ema20": float(last["EMA20"]),
            "ema50": float(last["EMA50"]),
            "ema200": float(last["EMA200"]),
            "trend": tfs["5m"]["regime"],
            "structure": tfs["5m"]["structure"],
            "volume_ratio": tfs["5m"]["volume_ratio"],
            "reasons": decision["reasons"],
            "timeframe_scores": {k: v["score"] for k, v in tfs.items()},
            "timeframe_directions": decision["directions"],
            "data_quality": True,
        }
    except Exception as exc:
        print(f"{symbol}: scan error: {exc}")
        return None
    finally:
        if PER_SYMBOL_DELAY_SECONDS:
            import time
            time.sleep(PER_SYMBOL_DELAY_SECONDS)


def scan_market_pro():
    results = []
    workers = max(1, min(int(MAX_WORKERS), len(SYMBOLS)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_scan_one, s, e, t) for s, (e, t) in SYMBOLS.items()]
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)
    return sorted(results, key=lambda x: x["score"], reverse=True)
