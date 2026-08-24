import os

from src.market_data_router import MarketDataRouter


class FakeAngel:
    def __init__(self, response=None, cooldown=300):
        self.response = response
        self.cooldown = cooldown

    def market_data_status(self):
        return {"cooldown_remaining": self.cooldown, "requests_remaining": 0 if self.cooldown else 10}

    def get_candles(self, params):
        raise AssertionError("Angel must not be called while its circuit breaker is active")


class FakeUpstox:
    def __init__(self, candles):
        self.candles = candles

    def available(self):
        return True

    def get_candles(self, symbol, interval_minutes=5):
        return self.candles


def test_router_falls_back_when_angel_is_in_cooldown(monkeypatch):
    candles = [["2026-08-24T11:25:00+05:30", 100, 101, 99, 100.5, 1000, 0]]
    router = MarketDataRouter(FakeAngel(cooldown=300))
    router.upstox = FakeUpstox(candles)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    router.mode = "auto"

    result, source = router.get_candles("RELIANCE", {"exchange": "NSE", "symboltoken": "2885"})

    assert result == candles
    assert source == "upstox"
    assert router.summary()["upstox_successes"] == 1


def test_router_fail_closed_without_configured_upstox(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    router = MarketDataRouter(FakeAngel(cooldown=300))

    class Unavailable:
        def available(self):
            return False

    router.upstox = Unavailable()
    result, source = router.get_candles("RELIANCE", {"exchange": "NSE", "symboltoken": "2885"})

    assert result is None
    assert source == "none"


def test_upstox_provider_mapping_contains_core_universe():
    from src.alternative_market_data import DEFAULT_INSTRUMENT_KEYS

    tier1 = (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
        "NIFTYFPI",
    )

    tier2 = (
        "RELIANCE",
        "TCS",
        "INFY",
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "AXISBANK",
    )

    for symbol in tier1:
        assert symbol in DEFAULT_INSTRUMENT_KEYS
        assert "|" in DEFAULT_INSTRUMENT_KEYS[symbol]

    for symbol in tier2:
        assert symbol not in DEFAULT_INSTRUMENT_KEYS
