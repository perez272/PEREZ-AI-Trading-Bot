from src.market_data_router import MarketDataRouter


class FakeAngel:
    def __init__(self, response=None, cooldown=0):
        self.response = response
        self.cooldown = cooldown
        self.calls = 0

    def market_data_status(self):
        return {"cooldown_remaining": self.cooldown, "requests_remaining": 10 if not self.cooldown else 0}

    def get_candles(self, params):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get_market_data(self, mode, exchange_tokens):
        self.calls += 1
        return self.response


def test_router_uses_angel_only_when_healthy():
    candles = [["2026-08-26T11:25:00+05:30", 100, 101, 99, 100.5, 1000, 0]]
    angel = FakeAngel(response={"status": True, "data": candles})
    router = MarketDataRouter(angel)

    result, source = router.get_candles("NIFTY", {"exchange": "NSE", "symboltoken": "999"})

    assert result == candles
    assert source == "angel_one"
    assert angel.calls == 1
    assert router.summary()["upstox_attempts"] == 0


def test_router_fails_closed_during_angel_cooldown():
    angel = FakeAngel(cooldown=300)
    router = MarketDataRouter(angel)

    result, source = router.get_candles("NIFTY", {"exchange": "NSE", "symboltoken": "999"})

    assert result is None
    assert source == "none"
    assert angel.calls == 0
    assert router.summary()["angel_skipped_cooldown"] == 1
    assert router.summary()["upstox_attempts"] == 0


def test_router_fails_closed_on_bad_angel_data():
    angel = FakeAngel(response={"status": True, "data": []})
    router = MarketDataRouter(angel)

    result, source = router.get_candles("NIFTY", {"exchange": "NSE", "symboltoken": "999"})

    assert result is None
    assert source == "none"
    assert angel.calls == 1
    assert router.summary()["upstox_attempts"] == 0


def test_router_provider_status_explicitly_disables_upstox():
    router = MarketDataRouter(FakeAngel())
    status = router.provider_status()

    assert status["mode"] == "angel"
    assert status["angel"] is not None
    assert status["upstox"]["enabled"] is False
    assert status["upstox"]["available"] is False
