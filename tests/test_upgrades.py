from src.options_trade_gate import OptionEvidence, validate_trade
from src.risk_manager import daily_summary
from src.upgrade_config import FRESHNESS_MAX_AGE_MINUTES, MINIMUM_SCORE, OPTIONS_MIN_SCORE, RESCAN_DELAY_SECONDS, SYMBOLS


def test_upgraded_universe_and_thresholds():
    assert len(SYMBOLS) >= 10
    assert MINIMUM_SCORE == 65
    assert OPTIONS_MIN_SCORE == 60
    assert RESCAN_DELAY_SECONDS <= 60
    assert FRESHNESS_MAX_AGE_MINUTES <= 5


def test_option_gate_rejects_missing_live_participation():
    result = validate_trade(OptionEvidence(symbol="NIFTY", option_type="CE", expiry="2026-08-27", ltp=100))
    assert result["eligible"] is False
    assert "NO_LIVE_OPTION_VOLUME" in result["reasons"]
    assert "NO_LIVE_OPTION_OI" in result["reasons"]


def test_daily_summary_empty_file(tmp_path):
    result = daily_summary(tmp_path / "missing.csv")
    assert result["closed_trades"] == 0
    assert result["pnl"] == 0.0
    assert result["consecutive_losses"] == 0
