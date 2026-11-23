from datetime import datetime, timedelta

from src.alternative_market_data import IST, UpstoxMarketData


def _client_with_responses(responses):
    client = UpstoxMarketData(access_token="test-token")
    client.available = lambda: True
    calls = []

    def fake_get(url, params=None):
        calls.append((url, params))
        return responses.pop(0)

    client._get = fake_get
    return client, calls


def test_option_chain_skips_expired_contracts_and_selects_nearest_future_expiry():
    today = datetime.now(IST).date()
    nearest = (today + timedelta(days=2)).isoformat()
    later = (today + timedelta(days=9)).isoformat()
    client, calls = _client_with_responses([
        {"data": [
            {"expiry": "2026-08-31"},
            {"expiry": later},
            {"expiry": nearest},
            {"expiry": "not-a-date"},
        ]},
        {"data": [{"expiry": nearest, "strike_price": 25000}]},
    ])

    result = client.get_option_chain("NIFTY")

    assert result == [{"expiry": nearest, "strike_price": 25000}]
    assert calls[1][1]["expiry_date"] == nearest


def test_option_chain_returns_none_when_contract_endpoint_has_only_expired_dates():
    client, calls = _client_with_responses([
        {"data": [{"expiry": "2026-08-31"}, {"expiry": "invalid"}]},
    ])

    assert client.get_option_chain("NIFTY") is None
    assert len(calls) == 1


def test_option_chain_rejects_explicit_expired_expiry_without_api_call():
    client, calls = _client_with_responses([])

    assert client.get_option_chain("NIFTY", expiry="2026-08-31") is None
    assert calls == []


def test_option_chain_rejects_mixed_or_mismatched_expiry_response():
    today = datetime.now(IST).date()
    requested = (today + timedelta(days=2)).isoformat()
    client, calls = _client_with_responses([
        {"data": [{"expiry": requested}]},
        {"data": [
            {"expiry": requested, "strike_price": 25000},
            {"expiry": "2026-08-31", "strike_price": 25050},
        ]},
    ])

    assert client.get_option_chain("NIFTY") is None
    assert calls[1][1]["expiry_date"] == requested


def test_option_chain_rejects_missing_expiry_metadata_in_chain_response():
    today = datetime.now(IST).date()
    requested = (today + timedelta(days=2)).isoformat()
    client, _ = _client_with_responses([
        {"data": [{"expiry": requested}]},
        {"data": [{"strike_price": 25000}]},
    ])

    assert client.get_option_chain("NIFTY") is None
