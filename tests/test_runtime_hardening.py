from datetime import datetime


def test_compact_option_id_from_trade_contract():
    from src.telegram_alert import _compact_option_id

    trade = {
        "symbol": "NIFTY",
        "contract": "NIFTY31AUG26CE25000",
    }
    assert _compact_option_id(trade) == "31AUG26NIFTYCE"


def test_compact_option_id_from_expiry_and_side():
    from src.telegram_alert import _compact_option_id

    trade = {
        "symbol": "BANKNIFTY",
        "option_type": "PE",
        "expiry": "2026-08-31",
        "contract": "BANKNIFTY",
    }
    assert _compact_option_id(trade) == "31AUG26BANKNIFTYPE"


def test_tier1_observer_uses_provider_refresh_ttl(tmp_path, monkeypatch):
    import src.tier1_option_observer as module

    class FakeUpstox:
        def __init__(self):
            self.calls = 0

        def available(self):
            return True

        def get_option_chain(self, symbol, expiry="current_week"):
            self.calls += 1
            return [{
                "instrument_key": f"NSE_FO|{symbol}|25000",
                "expiry": "2026-08-31",
                "strike_price": 25000,
                "trading_symbol": f"{symbol}31AUG26CE25000",
                "call_options": {
                    "instrument_key": f"NSE_FO|{symbol}|25000|CE",
                    "trading_symbol": f"{symbol}31AUG26CE25000",
                    "market_data": {"ltp": 100, "bid_price": 99, "ask_price": 101, "volume": 10, "oi": 100},
                },
                "put_options": {
                    "instrument_key": f"NSE_FO|{symbol}|25000|PE",
                    "trading_symbol": f"{symbol}31AUG26PE25000",
                    "market_data": {"ltp": 100, "bid_price": 99, "ask_price": 101, "volume": 10, "oi": 100},
                },
            }]

    fake = FakeUpstox()
    monkeypatch.setattr(module, "get_upstox_client", lambda: fake)
    monkeypatch.setattr(module, "CHAIN_REFRESH_TTL_SECONDS", 15)

    observer = module.Tier1OptionObserver(tmp_path / "observer.sqlite3")
    observer.observe_all()
    first_calls = fake.calls
    observer.observe_all()

    assert first_calls == len(module.TIER1_SYMBOLS)
    assert fake.calls == first_calls
