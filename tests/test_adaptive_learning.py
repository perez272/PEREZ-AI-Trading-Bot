import tempfile
from pathlib import Path

import src.adaptive_learning as al


def test_learning_is_neutral_before_minimum_samples():
    with tempfile.TemporaryDirectory() as td:
        old = al.DB_PATH
        al.DB_PATH = Path(td) / "adaptive.sqlite3"
        try:
            candidate = {
                "symbol": "NIFTY",
                "option_type": "CE",
                "percent_change": 6.0,
                "momentum_score": 8.0,
                "trend_score": 12.0,
                "volume_ratio": 2.0,
                "oi_change_pct": 12.0,
                "spread_pct": 0.4,
                "mtf_direction": "BUY",
            }
            al.remember_candidate(candidate, "e1")
            assert al.learning_signal(candidate)["status"] == "WARMING_UP"
        finally:
            al.DB_PATH = old


def test_learning_becomes_directional_after_wins_and_losses():
    with tempfile.TemporaryDirectory() as td:
        old = al.DB_PATH
        al.DB_PATH = Path(td) / "adaptive.sqlite3"
        try:
            candidate = {
                "symbol": "BANKNIFTY",
                "option_type": "PE",
                "percent_change": 8.0,
                "momentum_score": 9.0,
                "trend_score": 13.0,
                "volume_ratio": 2.5,
                "oi_change_pct": 15.0,
                "spread_pct": 0.35,
                "mtf_direction": "SELL",
            }
            for i in range(6):
                key = f"e{i}"
                al.remember_candidate(candidate, key)
                al.resolve_outcome(event_key=key, pnl=100.0, pnl_percent=2.0)
            learned = al.learning_signal(candidate)
            assert learned["status"] == "LEARNED"
            assert learned["adjustment"] > 0
            assert learned["wins"] == 6
            assert learned["losses"] == 0
        finally:
            al.DB_PATH = old
