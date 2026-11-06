import src.trade_engine as trade_engine


def _upstox_result():
    return {
        "status": "CONTRACT VALID",
        "contract": "NIFTY 23700 PE 08 SEP 26",
        "strike": 23700.0,
        "expiry": "2026-09-08",
        "ltp": 64.75,
        "token": "NSE_FO|TEST",
        "exchange": "NFO",
        "lotsize": 75,
        "affordability_score": 90,
        "data_source": "upstox_option_chain",
    }


def _angel_result():
    return {
        "status": "CONTRACT VALID",
        "symbol": "NIFTY 23700 PE 08 SEP 26",
        "strike": 23700.0,
        "expiry": "2026-09-08",
        "ltp": 64.75,
        "token": "ANGEL-TEST",
        "exchange": "NFO",
        "lotsize": 75,
        "affordability_score": 80,
    }


class FakeUpstox:
    def __init__(self, available=True, result=None):
        self._available = available
        self.result = result
        self.calls = 0
        self.preferred_strikes = []
        self.quote_calls = []

    def available(self):
        return self._available

    def get_full_quote(self, instrument_key):
        self.quote_calls.append(instrument_key)
        return {"depth": {"buy": [{"price": 100.0}], "sell": [{"price": 100.3}]}}

    def resolve_affordable_option(self, *args, preferred_strike=None):
        self.calls += 1
        self.preferred_strikes.append(preferred_strike)
        return self.result


def test_upstox_mode_uses_upstox_only(monkeypatch):
    upstox = FakeUpstox(result=_upstox_result())
    angel_calls = []

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "upstox")
    monkeypatch.setattr(trade_engine, "get_upstox_client", lambda: upstox)
    monkeypatch.setattr(
        trade_engine,
        "find_affordable_contract",
        lambda *args, **kwargs: angel_calls.append(args) or _angel_result(),
    )

    result = trade_engine.resolve_option_contract("NIFTY", 23700, "BUY PE")

    assert result["data_source"] == "upstox_option_chain"
    assert upstox.calls == 1
    assert upstox.preferred_strikes == [23750.0]
    assert upstox.quote_calls == ["NSE_FO|TEST"]
    assert angel_calls == []


def test_auto_prefers_upstox(monkeypatch):
    upstox = FakeUpstox(result=_upstox_result())
    angel_calls = []

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    monkeypatch.setattr(trade_engine, "get_upstox_client", lambda: upstox)
    monkeypatch.setattr(
        trade_engine,
        "find_affordable_contract",
        lambda *args, **kwargs: angel_calls.append(args) or _angel_result(),
    )

    result = trade_engine.resolve_option_contract("NIFTY", 23700, "BUY PE")

    assert result["data_source"] == "upstox_option_chain"
    assert upstox.calls == 1
    assert angel_calls == []


def test_auto_falls_back_to_angel_when_upstox_fails(monkeypatch):
    upstox = FakeUpstox(result={"status": "NO AFFORDABLE OPTION"})
    angel_calls = []

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "auto")
    monkeypatch.setattr(trade_engine, "get_upstox_client", lambda: upstox)

    def fake_angel(*args, **kwargs):
        angel_calls.append(args)
        return _angel_result()

    monkeypatch.setattr(trade_engine, "find_affordable_contract", fake_angel)

    result = trade_engine.resolve_option_contract("NIFTY", 23700, "BUY PE")

    assert result["status"] == "CONTRACT VALID"
    assert result["data_source"] == "angel_one_option_chain"
    assert upstox.calls == 1
    assert len(angel_calls) == 1


def test_angel_mode_does_not_call_upstox(monkeypatch):
    upstox = FakeUpstox(result=_upstox_result())
    angel_calls = []

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "angel")
    monkeypatch.setattr(trade_engine, "get_upstox_client", lambda: upstox)
    monkeypatch.setattr(
        trade_engine,
        "find_affordable_contract",
        lambda *args, **kwargs: angel_calls.append(args) or _angel_result(),
    )

    result = trade_engine.resolve_option_contract("NIFTY", 23700, "BUY PE")

    assert result["status"] == "CONTRACT VALID"
    assert upstox.calls == 0
    assert len(angel_calls) == 1


def test_expiry_parser_accepts_upstox_iso_datetime_and_angel_formats():
    assert trade_engine._parse_option_expiry("2026-10-30") is not None
    assert trade_engine._parse_option_expiry("2026-10-30T00:00:00+05:30") is not None
    assert trade_engine._parse_option_expiry("30OCT2026") is not None
    assert trade_engine._parse_option_expiry("30-Oct-2026") is not None
    assert trade_engine._parse_option_expiry("30/10/2026") is not None
    assert trade_engine._parse_option_expiry("not-an-expiry") is None


def test_naive_exchange_quote_timestamp_is_interpreted_as_ist():
    parsed = trade_engine._parse_option_quote_timestamp("30-Oct-2026 10:00:00")
    assert parsed is not None
    assert parsed.hour == 4 and parsed.minute == 30
    assert parsed.tzinfo is not None


def test_quote_timestamp_parser_rejects_malformed_value():
    assert trade_engine._parse_option_quote_timestamp("not-a-time") is None


def test_quote_normalizers_preserve_timestamp_and_top_of_book_quantities():
    from src.market_data_router import MarketDataRouter

    angel = MarketDataRouter._normalize_angel_option_quote({
        "ltp": 40.0,
        "exchFeedTime": "30-Oct-2026 10:00:00",
        "depth": {
            "buy": [{"price": 39.9, "quantity": 500}],
            "sell": [{"price": 40.1, "quantity": 600}],
        },
    })
    assert angel["timestamp"] == "30-Oct-2026 10:00:00"
    assert angel["depth"]["buy"][0]["quantity"] == 500
    assert angel["depth"]["sell"][0]["quantity"] == 600

    upstox = MarketDataRouter._normalize_upstox_option_quote({
        "last_price": 40.0,
        "last_trade_time": 1793337600000,
        "depth": {
            "buy": [{"price": 39.9, "quantity": 700}],
            "sell": [{"price": 40.1, "quantity": 800}],
        },
    })
    assert upstox["timestamp"] == 1793337600000
    assert upstox["depth"]["buy"][0]["quantity"] == 700
    assert upstox["depth"]["sell"][0]["quantity"] == 800


def test_create_trade_uses_ask_and_respects_planned_risk_multi_lot(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("ORDERS_ENABLED", "false")
    monkeypatch.setattr(trade_engine, "claim_contract", lambda *args: (True, "OK"))
    from src import active_position_guard
    monkeypatch.setattr(active_position_guard, "mark_claim_active", lambda *args: None)
    monkeypatch.setattr(trade_engine, "record_event", lambda *args, **kwargs: None)
    quote = {
        "ltp": 40.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "depth": {
            "buy": [{"price": 39.9, "quantity": 1000}],
            "sell": [{"price": 40.2, "quantity": 1000}],
        },
    }
    resolved = {
        "status": "CONTRACT VALID", "option_type": "CE", "contract": "NIFTY TEST CE",
        "exchange": "NFO", "token": "TEST", "expiry": (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "strike": 25000, "lotsize": 25, "ltp": 40.0, "live_option_quote": quote,
    }
    trade = trade_engine.create_trade("NIFTY", 25000, "BUY CE", 5000, resolved_contract=resolved)
    assert trade["status"] == "PAPER TRADE ACTIVE"
    assert trade["entry"] == 40.2
    assert trade["lots"] == 2
    assert trade["position_risk_inr"] <= 50.0
    assert trade["investment"] <= 4200.0


def test_create_trade_rejects_missing_or_future_quote_timestamp(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("ORDERS_ENABLED", "false")
    base = {
        "status": "CONTRACT VALID", "option_type": "CE", "contract": "NIFTY TEST CE",
        "exchange": "NFO", "token": "TEST", "expiry": (datetime.now().date() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "strike": 25000, "lotsize": 25, "ltp": 40.0,
    }
    book = {"depth": {"buy": [{"price": 39.9, "quantity": 100}], "sell": [{"price": 40.1, "quantity": 100}]}}
    missing = {**base, "live_option_quote": dict(book)}
    assert trade_engine.create_trade("NIFTY", 25000, "BUY CE", 5000, resolved_contract=missing)["reason"].startswith("OPTION_QUOTE_TIMESTAMP")
    future = {**base, "live_option_quote": {**book, "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}}
    assert "FUTURE" in trade_engine.create_trade("NIFTY", 25000, "BUY CE", 5000, resolved_contract=future)["reason"]
