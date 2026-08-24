from datetime import datetime, timedelta, timezone

from src.market_data_integrity import validate_candle_sources, validate_sources

NOW = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)


def quote(price=100.0, age=1):
    return {"price": price, "timestamp": NOW - timedelta(seconds=age)}


def candle(price=100.0, timestamp=None):
    return {"price": price, "timestamp": timestamp or datetime(2026, 8, 24, 9, 55, tzinfo=timezone.utc)}


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
    result = validate_sources({"FYERS": quote(0), "ANGEL": quote(-1)}, now=NOW)
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_invalid_timestamp_fails_closed():
    result = validate_sources({"FYERS": {"price": 100, "timestamp": "not-a-time"}}, now=NOW)
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_future_timestamp_fails_closed():
    result = validate_sources({"FYERS": quote(100, age=-10)}, now=NOW)
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"


def test_two_required_sources_need_corroboration():
    result = validate_sources({"FYERS": quote(100)}, now=NOW, required_sources=("FYERS", "ANGEL"))
    assert not result.ok


def test_closed_candle_agreement_passes():
    result = validate_candle_sources(
        {"ANGEL": candle(100.00), "FYERS": candle(100.20)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert result.ok
    assert result.reason == "FRESH_AGREED_CLOSED_CANDLE"
    assert result.sources == ("ANGEL", "FYERS")


def test_closed_candle_can_be_several_minutes_old_but_still_valid():
    ts = datetime(2026, 8, 24, 9, 55, tzinfo=timezone.utc)
    result = validate_candle_sources(
        {"ANGEL": candle(100, ts), "FYERS": candle(100.10, ts)},
        now=datetime(2026, 8, 24, 10, 4, tzinfo=timezone.utc),
        required_sources=("ANGEL", "FYERS"),
    )
    assert result.ok


def test_forming_candle_fails_closed():
    forming = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    result = validate_candle_sources(
        {"ANGEL": candle(100, forming), "FYERS": candle(100.1, forming)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok
    assert result.reason == "REQUIRED_SOURCE_MISSING_OR_STALE"


def test_different_candle_buckets_fail_closed():
    angel = datetime(2026, 8, 24, 9, 55, tzinfo=timezone.utc)
    fyers = datetime(2026, 8, 24, 9, 50, tzinfo=timezone.utc)
    result = validate_candle_sources(
        {"ANGEL": candle(100, angel), "FYERS": candle(100.1, fyers)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok
    assert result.reason == "REQUIRED_SOURCE_MISSING_OR_STALE"


def test_candle_price_disagreement_fails_closed():
    result = validate_candle_sources(
        {"ANGEL": candle(100), "FYERS": candle(101)},
        now=NOW,
        max_disagreement_pct=0.50,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok
    assert result.reason == "SOURCE_DISAGREEMENT"


def test_candle_stale_source_fails_closed():
    old = datetime(2026, 8, 24, 9, 40, tzinfo=timezone.utc)
    result = validate_candle_sources(
        {"ANGEL": candle(100, old), "FYERS": candle(100, old)},
        now=NOW,
        max_age_seconds=600,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok
    assert result.reason == "REQUIRED_SOURCE_MISSING_OR_STALE"


def test_candle_missing_source_fails_closed():
    result = validate_candle_sources(
        {"ANGEL": candle(100)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok


def test_candle_future_timestamp_fails_closed():
    future = NOW + timedelta(minutes=1)
    result = validate_candle_sources(
        {"ANGEL": candle(100, future), "FYERS": candle(100.1, future)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok


def test_candle_invalid_price_fails_closed():
    result = validate_candle_sources(
        {"ANGEL": candle(0), "FYERS": candle(-1)},
        now=NOW,
        required_sources=("ANGEL", "FYERS"),
    )
    assert not result.ok
    assert result.reason == "NO_FRESH_VALID_SOURCE"
