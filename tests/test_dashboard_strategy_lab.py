from src.dashboard_strategy_lab import _cepe, _entry_quality, _loss_analysis, _mfe_mae, build_lab


def test_strategy_lab_is_observation_only():
    result = build_lab()
    assert result["safety"] == "OBSERVATION_ONLY"
    assert result["counterfactual"]["status"] == "OBSERVATION_ONLY"
    assert "Risk manager remains authoritative" in result["guardrails"]


def test_empty_helpers_are_safe():
    assert _entry_quality([])["status"] == "UNAVAILABLE"
    assert _mfe_mae([])["status"] == "UNAVAILABLE"
    assert _loss_analysis([])["losses"] == 0
    assert _cepe([])["CE"]["samples"] == 0
    assert _cepe([])["PE"]["samples"] == 0
