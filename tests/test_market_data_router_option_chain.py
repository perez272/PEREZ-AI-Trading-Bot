from __future__ import annotations

from src import market_data_router
from src.market_data_router import MarketDataRouter


class FakeAngel:
    def __init__(self):
        self.calls = []

    def market_data_status(self):
        return {"cooldown_remaining": 0, "requests_remaining": 11}

    def get_market_data(self, mode, exchange_tokens):
        self.calls.append((mode, exchange_tokens))
        return {
            "status": True,
            "data": {
                "fetched": [
                    {
                        "symbolToken": token,
                        "tradingSymbol": f"NIFTY{token}CE",
                        "ltp": 101.5,
                        "tradeVolume": 1000,
                        "opnInterest": 5000,
                    }
                    for token in exchange_tokens["NFO"]
                ]
            },
        }


class FakeUpstox:
    def available(self):
        return True

    def get_option_chain(self, symbol, expiry="current_week"):
        return [{"symbol": symbol, "data_source": "upstox"}]


def _instruments():
    return [
        {"name": "NIFTY", "symbol": "NIFTY27AUG2624300CE", "token": "101", "exch_seg": "NFO", "instrumenttype": "OPTIDX", "expiry": "27AUG2026", "strike": "2430000"},
        {"name": "NIFTY", "symbol": "NIFTY27AUG2624300PE", "token": "102", "exch_seg": "NFO", "instrumenttype": "OPTIDX", "expiry": "27AUG2026", "strike": "2430000"},
        {"name": "NIFTY", "symbol": "NIFTY03SEP2624400CE", "token": "201", "exch_seg": "NFO", "instrumenttype": "OPTIDX", "expiry": "03SEP2026", "strike": "2440000"},
        {"name": "BANKNIFTY", "symbol": "BANKNIFTY27AUG2657000CE", "token": "301", "exch_seg": "NFO", "instrumenttype": "OPTIDX", "expiry": "27AUG2026", "strike": "5700000"},
    ]


def test_option_chain_uses_angel_full_market_data(monkeypatch):
    monkeypatch.setattr(market_data_router, "load_instruments", _instruments)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "angel")
    angel = FakeAngel()
    router = MarketDataRouter(angel)
    router.upstox = FakeUpstox()

    chain, source = router.get_option_chain("NIFTY", "current_week")

    assert source == "angel_one"
    assert chain is not None
    assert {row["token"] for row in chain} == {"101", "102"}
    assert all(row["data_source"] == "angel_one" for row in chain)
    assert len(angel.calls) == 1
    mode, exchange_tokens = angel.calls[0]
    assert mode == "FULL"
    assert exchange_tokens == {"NFO": ["101", "102"]}


def test_angel_mode_never_falls_back_to_upstox(monkeypatch):
    monkeypatch.setattr(market_data_router, "load_instruments", lambda: [])
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "angel")
    angel = FakeAngel()
    router = MarketDataRouter(angel)
    router.upstox = FakeUpstox()

    chain, source = router.get_option_chain("NIFTY")

    assert chain is None
    assert source == "none"
    assert angel.calls == []


def test_option_chain_caps_angel_request_at_50_tokens(monkeypatch):
    rows = []
    for index in range(60):
        rows.append({
            "name": "NIFTY",
            "symbol": f"NIFTY27AUG26{index:05d}CE",
            "token": str(index + 1),
            "exch_seg": "NFO",
            "instrumenttype": "OPTIDX",
            "expiry": "27AUG2026",
            "strike": str((24000 + index) * 100),
        })
    monkeypatch.setattr(market_data_router, "load_instruments", lambda: rows)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "angel")
    angel = FakeAngel()
    router = MarketDataRouter(angel)

    chain, source = router.get_option_chain("NIFTY")

    assert source == "angel_one"
    assert chain is not None
    assert len(angel.calls) == 1
    assert len(angel.calls[0][1]["NFO"]) == 50
