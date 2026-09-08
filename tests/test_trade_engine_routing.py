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

    def available(self):
        return self._available

    def resolve_affordable_option(self, *args):
        self.calls += 1
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
