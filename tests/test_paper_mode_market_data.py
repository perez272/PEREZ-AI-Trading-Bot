from src.market_data_router import MarketDataRouter


class AngelInCooldown:
    def market_data_status(self):
        return {"cooldown_remaining": 300, "requests_remaining": 0}

    def get_candles(self, params):
        raise AssertionError("Angel must not be called while its cooldown is active")


class UpstoxFallback:
    def available(self):
        return True

    def status(self):
        return {"provider": "upstox", "enabled": True, "configured": True, "available": True}

    def get_candles(self, symbol, interval_minutes=5):
        return [["2026-08-28T10:10:00+05:30", 100, 101, 99, 100.5, 1000, 0]]


def test_paper_mode_does_not_disable_auto_market_data_fallback(monkeypatch):
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    router = MarketDataRouter(AngelInCooldown())
    router.upstox = UpstoxFallback()

    candles, source = router.get_candles("NIFTY", {"exchange": "NSE", "symboltoken": "999"}, 5)

    assert candles
    assert source == "upstox"
    assert router.summary()["angel_skipped_cooldown"] == 1
    assert router.summary()["upstox_successes"] == 1
