from src.ensemble_engine import decision_band, ensemble_score
from src.regime_engine import classify_regime
from src.validation_engine import summarize_outcomes, validation_status


def test_regime_engine_is_deterministic():
    regime = classify_regime({"score": 82, "trend": "bullish", "volume_ratio": 2.2})
    assert regime.startswith("BULLISH|TRENDING|")


def test_ensemble_is_bounded_and_transparent():
    score, values = ensemble_score({"score": 90}, options_score=85, learned_confidence=80, regime_bonus=75)
    assert 0 <= score <= 100
    assert set(values) == {"market", "momentum", "breakout", "mean_reversion", "volume", "volatility", "regime", "options", "learned"}
    assert decision_band(score) in {"EXCEPTIONAL", "HIGH_CONVICTION", "PAPER_CANDIDATE", "WATCH", "NO_TRADE"}


def test_validation_metrics():
    stats = summarize_outcomes([{"pnl": 10}, {"pnl": -5}, {"pnl": 15}])
    assert stats["trades"] == 3
    assert stats["win_rate"] == 66.67
    assert stats["profit_factor"] == 5.0
    assert validation_status(stats) == "COLLECTING_EVIDENCE"
