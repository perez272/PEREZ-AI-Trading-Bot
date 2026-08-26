from pathlib import Path

from src.tier1_option_observer import Tier1OptionObserver


class FakeAngel:
    def __init__(self):
        self.calls = []

    def get_market_data(self, mode, exchange_tokens):
        self.calls.append((mode, exchange_tokens))
        token = exchange_tokens["NFO"][0]
        return {
            "status": True,
            "data": {
                "fetched": [
                    {
                        "symbolToken": token,
                        "tradingSymbol": "NIFTYTESTCE",
                        "ltp": 100,
                        "tradeVolume": 1000,
                        "opnInterest": 5000,
                    }
                ]
            },
        }


def test_tier1_observer_uses_angel_full_quote_only(tmp_path: Path):
    angel = FakeAngel()
    observer = Tier1OptionObserver(tmp_path / "tier1.sqlite3", angel_client=angel)
    observer._select_contracts = lambda: [
        {
            "name": "NIFTY",
            "expiry": "27AUG2026",
            "strike_value": 24300.0,
            "symbol": "NIFTY27AUG2624300CE",
            "token": "12345",
        }
    ]

    observer.observe_all()

    assert len(angel.calls) == 1
    mode, exchange_tokens = angel.calls[0]
    assert mode == "FULL"
    assert exchange_tokens == {"NFO": ["12345"]}
