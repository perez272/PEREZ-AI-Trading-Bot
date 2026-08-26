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
    # Accelerated test interval; production remains 1 request/second.
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
