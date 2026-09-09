import json

import pytest

from src import upstox_market_data as upstox
from src.market_data_validation import validate_against_upstox


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_upstox_ltp_uses_v3(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response({"status": "success", "data": {"NSE_EQ:ABC": {"last_price": 123.45}}})

    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "token")
    monkeypatch.setattr(upstox.requests, "get", fake_get)
    assert upstox.get_ltp("NSE_EQ|ABC") == pytest.approx(123.45)
    assert calls[0][0].startswith("https://api.upstox.com/v3/market-quote/ltp")


def test_instrument_mapping_is_strict(monkeypatch):
    monkeypatch.setenv("UPSTOX_INSTRUMENT_KEYS_JSON", json.dumps({"NIFTY": "NSE_INDEX|Nifty 50"}))
    assert upstox.instrument_keys()["NIFTY"] == "NSE_INDEX|Nifty 50"
    assert "BANKNIFTY" not in upstox.instrument_keys()


def test_enabled_validation_fails_closed_without_token(monkeypatch):
    monkeypatch.setenv("UPSTOX_ENABLED", "true")
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("UPSTOX_INSTRUMENT_KEYS_JSON", json.dumps({"NIFTY": "NSE_INDEX|Nifty 50"}))
    ok, details = validate_against_upstox("NIFTY", 25000.0)
    assert ok is False
    assert details["status"] == "MISSING_ACCESS_TOKEN"


def test_disabled_validation_does_not_change_existing_behavior(monkeypatch):
    monkeypatch.setenv("UPSTOX_ENABLED", "false")
    ok, details = validate_against_upstox("NIFTY", 25000.0)
    assert ok is True
    assert details["status"] == "DISABLED"

def test_session_vwap_uses_closed_positive_volume_candles(monkeypatch):
    candles = [
        ["2026-09-09T13:30:00+05:30", 144.0, 148.0, 142.0, 146.0, 100],
        ["2026-09-09T13:25:00+05:30", 140.0, 144.0, 138.0, 142.0, 200],
    ]
    monkeypatch.setattr(upstox, "get_intraday_candles", lambda instrument_key, interval_minutes: candles)
    monkeypatch.setattr(upstox, "datetime", __import__("src.upstox_market_data", fromlist=["datetime"]).datetime)
    value = upstox.get_session_vwap("NSE_FO|TEST", 5)
    expected = (((148.0 + 142.0 + 146.0) / 3.0) * 100 + ((144.0 + 138.0 + 142.0) / 3.0) * 200) / 300
    assert value == pytest.approx(expected)


def test_adapter_falls_back_to_upstox_session_vwap(monkeypatch):
    from src import options_engine_adapter as adapter
    monkeypatch.setattr(upstox, "get_session_vwap", lambda instrument_key, interval_minutes: 163.25)
    candidate = {
        "status": "CONTRACT VALID",
        "option_type": "PE",
        "contract": "BANKNIFTY 55300 PE 29 SEP 26",
        "exchange": "NFO",
        "token": "NSE_FO|69776",
        "expiry": "2026-09-29",
        "strike": 55300.0,
        "ltp": 170.0,
        "data_source": "upstox_option_chain",
        "live_option_quote": {
            "ltp": 170.0,
            "volume": 100000,
            "oi": 30000,
            "bid_price": 169.5,
            "ask_price": 170.5,
            "prev_oi": 25000,
        },
    }
    result = adapter.enrich_with_live_option_data(candidate)
    assert result["avg_price"] == pytest.approx(163.25)
    assert result["session_vwap"] == pytest.approx(163.25)
    assert result["vwap_source"] == "upstox_option_candles"
    assert result["vwap_score"] == pytest.approx(7.0)


def test_adapter_preserves_genuine_average_price(monkeypatch):
    from src import options_engine_adapter as adapter
    called = []
    monkeypatch.setattr(upstox, "get_session_vwap", lambda instrument_key, interval_minutes: called.append(True) or 999.0)
    candidate = {
        "status": "CONTRACT VALID",
        "option_type": "CE",
        "contract": "NIFTY 24000 CE 29 SEP 26",
        "exchange": "NFO",
        "token": "NSE_FO|12345",
        "expiry": "2026-09-29",
        "strike": 24000.0,
        "ltp": 120.0,
        "data_source": "upstox_option_chain",
        "live_option_quote": {
            "ltp": 120.0,
            "avgPrice": 110.0,
            "volume": 100000,
            "oi": 30000,
            "bid_price": 119.5,
            "ask_price": 120.5,
            "prev_oi": 25000,
        },
    }
    result = adapter.enrich_with_live_option_data(candidate)
    assert result["avg_price"] == pytest.approx(110.0)
    assert called == []
    assert result["vwap_score"] == pytest.approx(7.0)
