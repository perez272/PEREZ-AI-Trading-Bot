from src.future_value_engine import forecast, rank_selected


def _candidate():
    return {
        "symbol": "RELIANCE",
        "asset_type": "option",
        "ltp": 100.0,
        "trend_score": 85,
        "momentum_score": 80,
        "volume_score": 75,
        "vwap_score": 78,
        "structure_score": 72,
        "volatility_score": 60,
        "index_confirmation": 80,
        "oi_score": 70,
        "oi_change_score": 65,
        "iv_score": 55,
        "liquidity_score": 75,
    }


def test_forecast_is_bounded_and_directional():
    result = forecast(_candidate(), horizon="2h", news={"available": True, "score": 75})
    assert result["eligible"] is True
    f = result["forecast"]
    assert f["direction"] == "BULLISH"
    assert 0 < f["probability_up"] < 100
    assert f["expected_low"] <= f["current_price"] <= f["expected_high"]
    assert f["target"] > f["current_price"]


def test_missing_news_does_not_create_positive_evidence():
    result = forecast(_candidate(), news={})
    assert result["eligible"] is True
    assert "news unavailable" in result["forecast"]["blockers"]


def test_rank_selected_does_not_expand_universe():
    results = rank_selected([_candidate()])
    assert len(results) == 1
    assert results[0]["symbol"] == "RELIANCE"
