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


def test_one_market_data_rate_limit_does_not_create_global_or_candle_lock(tmp_path):
    class _RateLimitedApi:
        def getMarketData(self, mode, exchange_tokens):
            return {"status": False, "message": "Access denied because of exceeding access rate"}

    client = AngelClient(_RateLimitedApi())
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")

    assert client.get_market_data("LTP", {"NSE": ["1"]}) is None
    status = client.market_data_status()
    assert status["cooldown_remaining"] == 0.0
    assert status["market_data_cooldown_remaining"] > 0
    assert status["candle_cooldown_remaining"] == 0.0
    assert status["rate_limit_events"] == 1


def test_three_rate_limits_arm_global_circuit_breaker(tmp_path):
    class _RateLimitedApi:
        def getMarketData(self, mode, exchange_tokens):
            return {"status": False, "message": "Access denied because of exceeding access rate"}

    client = AngelClient(_RateLimitedApi())
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.MARKET_DATA_REQUEST_INTERVAL = 0.0

    for _ in range(3):
        assert client.get_market_data("LTP", {"NSE": ["1"]}) is None
        # Endpoint cooldown is test-only accelerated so each event can be
        # recorded without waiting the production 60-second cooldown.
        with open(client.MARKET_DATA_BUDGET_FILE, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        state["market_data_cooldown_until"] = 0.0
        with open(client.MARKET_DATA_BUDGET_FILE, "w", encoding="utf-8") as handle:
            json.dump(state, handle)

    status = client.market_data_status()
    assert status["rate_limit_events"] == 3
    assert status["cooldown_remaining"] > 0


def test_market_data_endpoint_cooldown_does_not_block_fresh_candles(tmp_path):
    class _MixedApi:
        def getMarketData(self, mode, exchange_tokens):
            return {"status": False, "message": "Access denied because of exceeding access rate"}

        def getCandleData(self, params):
            return {"status": True, "data": [["2026-08-26T09:20:00+05:30", 1, 1, 1, 1, 1]]}

    client = AngelClient(_MixedApi())
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")
    client.CANDLE_REQUEST_INTERVAL = 0.01

    assert client.get_market_data("LTP", {"NSE": ["1"]}) is None
    candles = client.get_candles({"symboltoken": "NIFTY", "interval": "FIVE_MINUTE"})
    assert candles is not None
    assert len(candles["data"]) == 1


def test_legacy_global_state_without_shared_timestamp_does_not_preserve_stale_lock(tmp_path):
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"requests": [], "cooldown_until": time.monotonic() + 300}), encoding="utf-8")
    api = _FiveIndexFakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(budget)
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")
    client.CANDLE_REQUEST_INTERVAL = 0.01

    assert client.get_candles({"symboltoken": "NIFTY"}) is not None
    assert api.calls == ["NIFTY"]
