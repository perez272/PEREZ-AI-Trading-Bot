import json
import time

from src.broker.angel_client import AngelClient


class _FiveIndexFakeSmartApi:
    def __init__(self):
        self.calls = []

    def getCandleData(self, params):
        self.calls.append(params["symboltoken"])
        return {"status": True, "data": []}


def test_five_tier1_indices_are_paced_without_candle_lock(tmp_path):
    api = _FiveIndexFakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")
    # Accelerated test interval; production remains conservative.
    client.CANDLE_REQUEST_INTERVAL = 0.01

    tokens = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    started = time.monotonic()
    for token in tokens:
        result = client.get_candles({"interval": "FIVE_MINUTE", "symboltoken": token})
        assert result == {"status": True, "data": []}
    elapsed = time.monotonic() - started

    assert api.calls == tokens
    assert elapsed >= 0.035
    assert client.market_data_status()["candle_cooldown_remaining"] == 0.0
    assert client.market_data_status()["requests_in_window"] == 5


def test_shared_pacing_serializes_separate_angel_clients(tmp_path):
    api = _FiveIndexFakeSmartApi()
    budget = str(tmp_path / "budget.json")
    candle_a = str(tmp_path / "candle_a.json")
    candle_b = str(tmp_path / "candle_b.json")
    first = AngelClient(api)
    second = AngelClient(api)
    for client in (first, second):
        client.MARKET_DATA_BUDGET_FILE = budget
        client.CANDLE_REQUEST_INTERVAL = 0.02
    first.CANDLE_COOLDOWN_FILE = candle_a
    second.CANDLE_COOLDOWN_FILE = candle_b

    assert first.get_candles({"symboltoken": "NIFTY"}) is not None
    started = time.monotonic()
    assert second.get_candles({"symboltoken": "BANKNIFTY"}) is not None
    assert time.monotonic() - started >= 0.015
    assert api.calls == ["NIFTY", "BANKNIFTY"]


def test_non_candle_rate_limit_does_not_create_candle_lock(tmp_path):
    class _RateLimitedApi:
        def getMarketData(self, mode, exchange_tokens):
            return {"status": False, "message": "Access denied because of exceeding access rate"}

    client = AngelClient(_RateLimitedApi())
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")

    assert client.get_market_data("LTP", {"NSE": ["1"]}) is None
    status = client.market_data_status()
    assert status["cooldown_remaining"] > 0
    assert status["candle_cooldown_remaining"] == 0.0


def test_legacy_global_state_without_shared_timestamp_remains_compatible(tmp_path):
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"requests": [], "cooldown_until": 0.0}), encoding="utf-8")
    api = _FiveIndexFakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(budget)
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")
    client.CANDLE_REQUEST_INTERVAL = 0.01

    assert client.get_candles({"symboltoken": "NIFTY"}) is not None
    assert api.calls == ["NIFTY"]
