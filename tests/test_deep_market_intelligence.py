from pathlib import Path

from src.deep_market_intelligence import DeepMarketIntelligence


def _snapshot(**overrides):
    data = {
        "symbol": "NIFTY",
        "score": 70,
        "close": 25000,
        "rsi": 62,
        "percent_change": 0.8,
        "breakout_strength": 0.4,
        "body_strength": 0.8,
        "atr_pct": 0.7,
        "volume_ratio": 2.0,
        "signal": "BUY CE",
        "trend": "BULLISH",
        "m15_trend": "BULLISH",
        "h1_trend": "BULLISH",
        "data_source": "angel",
        "market_data_fresh": True,
        "market_integrity_ok": True,
    }
    data.update(overrides)
    return data


def test_process_uses_supplied_snapshot_without_provider_calls(tmp_path: Path):
    engine = DeepMarketIntelligence(tmp_path / "deep.sqlite3")
    result = engine.process([_snapshot()], observed_ts="2026-08-29T10:00:00+05:30")
    assert len(result) == 1
    assert result[0]["engine"] == "shared_snapshot"
    assert result[0]["deep_score"] > 70
    assert result[0]["regime"] == "HIGH_MOVE"
    assert "volume_expansion" in result[0]["reasons"]
    assert engine.stats()["snapshots"] == 1


def test_second_snapshot_detects_acceleration(tmp_path: Path):
    engine = DeepMarketIntelligence(tmp_path / "deep.sqlite3")
    engine.process([_snapshot(percent_change=0.1)], observed_ts="2026-08-29T10:00:00+05:30")
    result = engine.process([_snapshot(percent_change=0.7)], observed_ts="2026-08-29T10:00:05+05:30")
    assert result[0]["acceleration"] == 0.6
    assert "acceleration" in result[0]["reasons"]


def test_empty_input_is_safe(tmp_path: Path):
    engine = DeepMarketIntelligence(tmp_path / "deep.sqlite3")
    assert engine.process([]) == []
    assert engine.stats()["snapshots"] == 0
