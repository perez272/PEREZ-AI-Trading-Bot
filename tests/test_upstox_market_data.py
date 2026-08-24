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
