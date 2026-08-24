from src.index_momentum_strategy import build_dynamic_exits, select_index_momentum_candidate


def _candidate(symbol="SENSEX", signal="BUY CE", score=60, rsi=62, volume_ratio=1.6):
    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "market_data_fresh": True,
        "market_integrity_ok": True,
        "mtf_aligned": True,
        "m15_trend": "BULLISH" if signal == "BUY CE" else "BEARISH",
        "h1_trend": "BULLISH" if signal == "BUY CE" else "BEARISH",
    }


def test_strong_sensex_momentum_candidate_is_selected():
    result = select_index_momentum_candidate([_candidate()])
    assert result is not None
    assert result["symbol"] == "SENSEX"
    assert result["signal"] == "BUY CE"
    assert result["strategy"] == "INDEX_MOMENTUM_SCALP"
    assert result["momentum_score"] >= 72


def test_stale_or_unaligned_candidate_is_rejected():
    candidate = _candidate()
    candidate["market_data_fresh"] = False
    assert select_index_momentum_candidate([candidate]) is None

    candidate = _candidate()
    candidate["mtf_aligned"] = False
    assert select_index_momentum_candidate([candidate]) is None


def test_dynamic_exits_are_bounded_and_ordered():
    exits = build_dynamic_exits(49.0, 0.0, 49.0)
    assert exits["stop_loss"] < 49.0 < exits["target1"] < exits["target2"]
    assert exits["target1_pct"] == 0.15
    assert exits["target2_pct"] == 0.30
