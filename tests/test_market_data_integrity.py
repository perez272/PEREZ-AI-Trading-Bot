from datetime import datetime, timedelta, timezone

from src.market_data_integrity import validate_sources

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)


def quote(price=100.0, age=1):
    return {"price": price, "timestamp": NOW - timedelta(seconds=age)}


def test_fresh_agreement_passes():
    result = validate_sources(
        {"FYERS": quote(100), "ANGEL": quote(100.05)},
        now=NOW,
        required_sources=("FYERS", "ANGEL"),
    )
    assert result.ok
    assert result.reason == "FRESH_AGREED_DATA"


def test_source_disagreement_fails_closed():
    result = validate_sources(
        {"FYERS": quote(100), "ANGEL": quote(101)},
        now=NOW,
        max_disagreement_pct=0.25,
        required_sources=("FYERS", "ANGEL"),
    )
    assert not result.ok
    assert result.reason == "SOURCE_DISAGREEMENT"


def test_stale_data_fails_closed():
    result = validate_sources(
        {"FYERS": quote(100, age=31), "ANGEL": quote(100.02, age=31)},
        now=NOW,
        max_age_seconds=30,
        required_sources=("FYERS", "ANGEL"),
    )
    assert not result.ok
    assert result.reason == "REQUIRED_SOURCE_MISSING_OR_STALE"


def test_missing_required_source_fails_closed():
    result = validate_sources(
        {"FYERS": quote(100)},
        now=NOW,
        required_sources=("FYERS", "ANGEL"),
    )
    assert not result.ok
    assert result.reason == "REQUIRED_SOURCE_MISSING_OR_STALE"


def test_missing_all_sources_fails_closed():
    result = validate_sources({}, now=NOW)
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_invalid_price_fails_closed():
    result = validate_sources(
        {"FYERS": quote(0), "ANGEL": quote(-1)},
        now=NOW,
    )
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_invalid_timestamp_fails_closed():
    result = validate_sources(
        {"FYERS": {"price": 100, "timestamp": "not-a-time"}},
        now=NOW,
    )
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_future_timestamp_fails_closed():
    result = validate_sources(
        {"FYERS": quote(100, age=-10)},
        now=NOW,
    )
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_two_required_sources_need_corroboration():
    result = validate_sources(
        {"FYERS": quote(100)},
        now=NOW,
        required_sources=("FYERS", "ANGEL"),
    )
    assert not result.ok
