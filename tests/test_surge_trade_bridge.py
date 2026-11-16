from datetime import datetime, timedelta, timezone

from src.surge_trade_bridge import _underlying_move_5m_pct


class FakeClient:
    def __init__(self, candles):
        self.candles = candles

    def get_candles(self, symbol, interval_minutes=1):
        assert symbol == "NIFTY"
        assert interval_minutes == 1
        return self.candles


def candles_from_closes(closes, start=None):
    start = start or (datetime.now(timezone.utc) - timedelta(minutes=5))
    return [
        [(start + timedelta(minutes=i)).isoformat(), close, close, close, close, 1000]
        for i, close in enumerate(closes)
    ]


def test_underlying_move_requires_six_candles():
    assert _underlying_move_5m_pct(FakeClient(candles_from_closes([100, 101, 102])), "NIFTY") is None


def test_underlying_move_uses_exact_five_minute_window():
    result = _underlying_move_5m_pct(
        FakeClient(candles_from_closes([100, 101, 102, 103, 104, 105])),
        "NIFTY",
    )
    assert result is not None
    assert abs(result - 5.0) < 1e-9


def test_underlying_move_rejects_stale_candles():
    old_start = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert _underlying_move_5m_pct(
        FakeClient(candles_from_closes([100, 101, 102, 103, 104, 105], old_start)),
        "NIFTY",
    ) is None


def test_underlying_move_rejects_gapped_candles():
    rows = candles_from_closes([100, 101, 102, 103, 104, 105])
    rows[-1][0] = (datetime.fromisoformat(rows[-2][0]) + timedelta(minutes=3)).isoformat()
    assert _underlying_move_5m_pct(FakeClient(rows), "NIFTY") is None
