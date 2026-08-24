from datetime import datetime, timedelta, timezone

from src.broker.angel_client import AngelClient
import src.fyers_market_data as fyers_market_data

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
CLOSED = (NOW - timedelta(minutes=5)).isoformat()
FORMING = NOW.isoformat()
OLD = (NOW - timedelta(minutes=20)).isoformat()
PRIOR = (NOW - timedelta(minutes=10)).isoformat()


def candle(price, timestamp=CLOSED):
    return [timestamp, price, price + 1, price - 1, price, 1000]


class FakeAPI:
    def __init__(self, response):
        self.response = response

    def getCandleData(self, params):
        return self.response


def make_client(angel_response):
    client = AngelClient(FakeAPI(angel_response))
    client._reserve_market_data_request = lambda *args, **kwargs: True
    client._retry = lambda func, *args, **kwargs: func(*args, **kwargs)
    return client


def latest_closed_timestamp():
    now = datetime.now(timezone.utc)
    bucket_minute = (now.minute // 5) * 5
    bucket = now.replace(
        minute=bucket_minute,
        second=0,
        microsecond=0,
    )
    return (bucket - timedelta(minutes=5)).isoformat()


def test_router_accepts_only_corroborated_closed_candle(monkeypatch):
    # Use the real clock, but construct the latest completed 5-minute
    # candle deterministically. Keep the timestamp 1 second after the
    # bucket start so it is safely inside the validator's age window.
    now = datetime.now(timezone.utc)
    current_bucket = now.replace(
        minute=(now.minute // 5) * 5,
        second=0,
        microsecond=0,
    )
    # Timestamp must belong to the latest COMPLETED 5-minute candle,
    # not the current/forming candle.
    latest_closed_bucket = current_bucket - timedelta(minutes=5)
    ts = (latest_closed_bucket + timedelta(seconds=1)).isoformat()

    angel = {"status": True, "data": [candle(100.0, ts)]}
    fyers = {"status": True, "data": [candle(100.2, ts)]}

    monkeypatch.setattr(
        fyers_market_data,
        "get_candles",
        lambda symbol, exchange: fyers,
    )

    client = make_client(angel)

    result = client.get_candles(
        {"exchange": "NSE", "symbol": "NIFTY"}
    )

    assert result is not None
    assert result["data_source"] == "ANGEL+FYERS_CORROBORATED"
    assert result["integrity"]["ok"] is True
    assert set(result["integrity"]["sources"]) == {"ANGEL", "FYERS"}

def test_router_rejects_source_disagreement(monkeypatch):
    angel = {"status": True, "data": [candle(100.0)]}
    fyers = {"status": True, "data": [candle(101.0)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    assert make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_rejects_missing_fyers(monkeypatch):
    angel = {"status": True, "data": [candle(100.0)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: None)

    assert make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_rejects_missing_angel(monkeypatch):
    fyers = {"status": True, "data": [candle(100.0)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    assert make_client(None).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_rejects_stale_same_bucket(monkeypatch):
    angel = {"status": True, "data": [candle(100.0, OLD)]}
    fyers = {"status": True, "data": [candle(100.1, OLD)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    assert make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_rejects_forming_candle(monkeypatch):
    angel = {"status": True, "data": [candle(100.0, FORMING)]}
    fyers = {"status": True, "data": [candle(100.1, FORMING)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    assert make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_rejects_different_candle_buckets(monkeypatch):
    angel = {"status": True, "data": [candle(100.0, CLOSED)]}
    fyers = {"status": True, "data": [candle(100.1, PRIOR)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    assert make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"}) is None


def test_router_never_returns_angel_only(monkeypatch):
    angel = {"status": True, "data": [candle(100.0)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: None)

    result = make_client(angel).get_candles({"exchange": "NSE", "symbol": "NIFTY"})
    assert result is None


def test_router_never_returns_fyers_only(monkeypatch):
    fyers = {"status": True, "data": [candle(100.0)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)

    result = make_client(None).get_candles({"exchange": "NSE", "symbol": "NIFTY"})
    assert result is None
