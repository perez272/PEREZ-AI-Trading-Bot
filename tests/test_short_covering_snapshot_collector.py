from datetime import datetime, timedelta, timezone

import pytest

from src.short_covering_snapshot_collector import ShortCoveringSnapshotCollector


class FakeClient:
    def __init__(self):
        self.chain = []

    def get_option_chain(self, symbol, expiry=None):
        return self.chain


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=60):
        self.value += timedelta(seconds=seconds)


def chain_row(*, ltp=100, oi=1000, volume=1000, expiry="2026-11-03"):
    return {
        "expiry": expiry,
        "strike_price": 23400,
        "underlying_spot_price": 23450,
        "call_options": {
            "instrument_key": "NSE_FO|NIFTY_CALL_23400",
            "market_data": {
                "ltp": ltp, "oi": oi, "volume": volume,
                "bid_price": ltp - 0.5, "ask_price": ltp + 0.5,
            },
        },
        "put_options": {
            "instrument_key": "NSE_FO|NIFTY_PUT_23400",
            "market_data": {
                "ltp": 80, "oi": 1200, "volume": volume,
                "bid_price": 79.5, "ask_price": 80.5,
            },
        },
    }


def test_persists_snapshots_without_using_previous_session_oi(tmp_path):
    client, clock = FakeClient(), Clock()
    collector = ShortCoveringSnapshotCollector(client, tmp_path / "obs.sqlite3", clock=clock)
    client.chain = [chain_row()]
    first = collector.capture("NIFTY")
    assert first["contracts_saved"] == 2
    assert first["mode"] == "OBSERVATION_ONLY"
    assert first["signals"] == []
    clock.advance()
    client.chain = [chain_row(ltp=101, oi=990, volume=1100)]
    second = collector.capture("NIFTY")
    assert second["signals"] == []
    assert second["contracts_evaluated"] == 0


def test_confirms_only_after_five_prior_interval_volume_baselines(tmp_path):
    client, clock = FakeClient(), Clock()
    collector = ShortCoveringSnapshotCollector(client, tmp_path / "obs.sqlite3", clock=clock)
    for index in range(6):
        client.chain = [chain_row(ltp=100, oi=1000, volume=1000 + index * 100)]
        result = collector.capture("NIFTY")
        assert result["signals"] == []
        clock.advance()
    client.chain = [chain_row(ltp=125, oi=800, volume=1900)]
    result = collector.capture("NIFTY")
    call_signal = next(
        item for item in result["signals"] if item["option_type"] == "CE"
    )
    assert call_signal["oi_change_pct"] == pytest.approx(-20.0)
    assert call_signal["price_change_pct"] == pytest.approx(25.0)
    assert call_signal["volume_ratio"] == pytest.approx(4.0)
    assert call_signal["reason"] == "PRICE_UP_INTRADAY_OI_DOWN_VOLUME_EXPANSION"


def test_rejects_wrong_expiry_and_invalid_contracts(tmp_path):
    client, clock = FakeClient(), Clock()
    collector = ShortCoveringSnapshotCollector(client, tmp_path / "obs.sqlite3", clock=clock)
    client.chain = [chain_row(expiry="2026-11-10")]
    with pytest.raises(RuntimeError, match="No valid option contracts"):
        collector.capture("NIFTY", expiry="2026-11-03")


def test_rejects_empty_chain(tmp_path):
    client, clock = FakeClient(), Clock()
    collector = ShortCoveringSnapshotCollector(client, tmp_path / "obs.sqlite3", clock=clock)
    with pytest.raises(RuntimeError, match="No Upstox option chain"):
        collector.capture("NIFTY")


def test_rejects_naive_clock(tmp_path):
    client = FakeClient()
    collector = ShortCoveringSnapshotCollector(
        client, tmp_path / "obs.sqlite3",
        clock=lambda: datetime(2026, 11, 3, 4, 0),
    )
    client.chain = [chain_row()]
    with pytest.raises(ValueError, match="timezone-aware"):
        collector.capture("NIFTY")


def test_interval_gap_out_of_range_fails_closed(tmp_path):
    client, clock = FakeClient(), Clock()
    collector = ShortCoveringSnapshotCollector(client, tmp_path / "obs.sqlite3", clock=clock)
    for index in range(6):
        client.chain = [chain_row(volume=1000 + index * 100)]
        collector.capture("NIFTY")
        clock.advance(60)
    clock.advance(300)
    client.chain = [chain_row(ltp=125, oi=800, volume=1900)]
    result = collector.capture("NIFTY")
    assert result["signals"] == []
    assert any(item["reason"] == "SNAPSHOT_INTERVAL_OUT_OF_RANGE" for item in result["analysis"])


def test_invalid_configuration_fails_fast(tmp_path):
    with pytest.raises(ValueError):
        ShortCoveringSnapshotCollector(FakeClient(), tmp_path / "x.db", oi_drop_threshold=5)
