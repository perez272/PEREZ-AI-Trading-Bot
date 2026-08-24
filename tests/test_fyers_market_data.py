from src.fyers_market_data import FyersMarketData


def test_fyers_disabled_without_credentials(monkeypatch):
    monkeypatch.setenv("FYERS_ENABLED", "true")
    monkeypatch.delenv("FYERS_APP_ID", raising=False)
    monkeypatch.delenv("FYERS_ACCESS_TOKEN", raising=False)
    client = FyersMarketData()
    assert client.available() is False


def test_fyers_candle_validation_and_sorting(monkeypatch):
    monkeypatch.setenv("FYERS_ENABLED", "true")
    monkeypatch.setenv("FYERS_APP_ID", "test-app")
    monkeypatch.setenv("FYERS_ACCESS_TOKEN", "test-token")
    client = FyersMarketData()

    def fake_get(path, params):
        assert path == "/history"
        assert params["resolution"] == "5"
        return {
            "s": "ok",
            "candles": [
                [200, 101, 102, 100, 101.5, 500],
                [100, 100, 101, 99, 100.5, 400],
                [300, 105, 104, 103, 104, 100],  # invalid high/low relationship
                [400, 105, 106, 104, 105, -1],  # invalid volume
            ],
        }

    client._get = fake_get
    candles = client.get_candles("RELIANCE", interval_minutes=5)
    assert [row[0] for row in candles] == [100, 200]


def test_fyers_default_symbol_mapping_contains_core_universe():
    from src.fyers_market_data import DEFAULT_SYMBOLS

    for symbol in ("NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"):
        assert symbol in DEFAULT_SYMBOLS
        assert ":" in DEFAULT_SYMBOLS[symbol]
