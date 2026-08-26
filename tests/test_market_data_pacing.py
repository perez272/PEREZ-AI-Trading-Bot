import json
import time

from src.broker.angel_client import AngelClient


class _FakeSmartApi:
    def __init__(self):
        self.calls = 0

    def getCandleData(self, params):
        self.calls += 1
        return {"status": True, "data": []}


def test_market_data_request_is_paced(tmp_path):
    api = _FakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle_cooldown.json")
    # Use a deliberately larger interval so the assertion is not sensitive to
    # sub-millisecond scheduler/timing jitter while still exercising the real
    # wait-before-request pacing path.
    client.CANDLE_REQUEST_INTERVAL = 0.05

    started = time.monotonic()
    first = client.get_candles({"interval": "FIVE_MINUTE"})
    first_finished = time.monotonic()
    second = client.get_candles({"interval": "FIVE_MINUTE"})
    second_finished = time.monotonic()

    assert first == {"status": True, "data": []}
    assert second == {"status": True, "data": []}
    assert api.calls == 2
    assert first_finished - started < 0.02
    assert second_finished - first_finished >= 0.045
    status = client.market_data_status()
    assert status["requests_in_window"] == 2
    assert status["requests_remaining"] == client.MARKET_DATA_BUDGET_MAX_REQUESTS - 2


def test_global_cooldown_blocks_without_touching_provider(tmp_path):
    api = _FakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle_cooldown.json")
    with open(client.MARKET_DATA_BUDGET_FILE, "w", encoding="utf-8") as handle:
        json.dump({
            "requests": [],
            "cooldown_until": time.monotonic() + 30,
            "global_breaker_armed": True,
            "rate_limit_events": [
                time.monotonic() - 2,
                time.monotonic() - 1,
                time.monotonic(),
            ],
        }, handle)

    result = client.get_candles({"interval": "FIVE_MINUTE"})

    assert result is None
    assert api.calls == 0
    status = client.market_data_status()
    assert status["cooldown_remaining"] > 0


def test_legacy_cooldown_does_not_block_but_armed_breaker_does(tmp_path):
    api = _FakeSmartApi()
    client = AngelClient(api)
    client.MARKET_DATA_BUDGET_FILE = str(tmp_path / "budget.json")
    client.CANDLE_COOLDOWN_FILE = str(tmp_path / "candle.json")

    # Legacy state: must not block.
    Path = __import__("pathlib").Path
    Path(client.MARKET_DATA_BUDGET_FILE).write_text(
        json.dumps({
            "requests": [],
            "cooldown_until": time.monotonic() + 300,
        }),
        encoding="utf-8",
    )
    assert client.get_candles({"symboltoken": "NIFTY"}) is not None
    assert api.calls == 1

    # Real armed breaker: must block.
    Path(client.MARKET_DATA_BUDGET_FILE).write_text(
        json.dumps({
            "requests": [],
            "cooldown_until": time.monotonic() + 30,
            "global_breaker_armed": True,
            "rate_limit_events": [
                time.monotonic() - 2,
                time.monotonic() - 1,
                time.monotonic(),
            ],
        }),
        encoding="utf-8",
    )
    assert client.get_candles({"symboltoken": "BANKNIFTY"}) is None
    assert api.calls == 1
