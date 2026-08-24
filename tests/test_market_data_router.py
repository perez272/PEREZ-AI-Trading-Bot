from datetime import datetime, timezone

from src.broker.angel_client import AngelClient
import src.fyers_market_data as fyers_market_data

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
CLOSED = "2026-08-24T09:55:00+00:00"
FORMING = "2026-08-24T10:00:00+00:00"
OLD = "2026-08-24T09:40:00+00:00"
PRIOR = "2026-08-24T09:50:00+00:00"


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


def test_router_accepts_only_corroborated_closed_candle(monkeypatch):
    angel = {"status": True, "data": [candle(100.0)]}
    fyers = {"status": True, "data": [candle(100.2)]}
    monkeypatch.setattr(fyers_market_data, "get_candles", lambda symbol, exchange: fyers)
    client = make_client(angel)

    result = client.get_candles({"exchange": "NSE", "symbol": "NIFTY"})

    assert result is not None
    assert result["data_source"] == "ANGEL+FYERS_CORROBORATED"
    assert result["integrity"]["ok"] is True


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
