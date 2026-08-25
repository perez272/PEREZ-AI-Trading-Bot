import json
import sqlite3


def test_tier1_observer_persists_observation_and_stats(tmp_path):
    from src.tier1_option_observer import Tier1OptionObserver

    observer = Tier1OptionObserver(tmp_path / "moves.sqlite3")
    chain = [{
        "instrument_key": "NSE_INDEX|NIFTY",
        "expiry": "2026-08-27",
        "strike_price": 25000,
        "call_options": {
            "instrument_key": "NFO|NIFTYCE",
            "trading_symbol": "NIFTYCE",
            "market_data": {"ltp": 50, "bid_price": 49.9, "ask_price": 50.1, "volume": 100, "oi": 1000},
        },
        "put_options": {
            "instrument_key": "NFO|NIFTYPE",
            "trading_symbol": "NIFTYPE",
            "market_data": {"ltp": 40, "bid_price": 39.9, "ask_price": 40.1, "volume": 100, "oi": 1000},
        },
    }]

    observer.observe("NIFTY", chain, "2026-08-25T03:30:00+00:00")
    stats = observer.stats()
    assert stats["observations"] == 1
    assert stats["surge_events"] == 0


def test_learning_status_reads_persisted_telemetry(tmp_path, monkeypatch):
    import src.learning_status as status

    monkeypatch.setattr(status, "STATUS_PATH", tmp_path / "learning_status.json")
    monkeypatch.setattr(status, "daily_summary", lambda: {"closed_trades": 0, "pnl": 0.0, "consecutive_losses": 0, "worst_loss": 0.0})

    status.record_cycle(observations=1, rejections=2, lessons_events=3, events=[{"type": "EARLY_EXPLOSIVE"}])
    payload = json.loads((tmp_path / "learning_status.json").read_text())
    assert payload["rejections"] == 2
    assert payload["lessons_events"] == 3
    assert payload["last_events"][0]["type"] == "EARLY_EXPLOSIVE"
