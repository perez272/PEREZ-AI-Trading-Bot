from src.surge_confirmation import confirm


def test_continuation_pullback_can_confirm():
    # Mirrors the observed high-MFE pattern: negative 1m pullback while
    # 3m/5m continuation, tight spread, controlled acceleration and score
    # remain strong.
    result = confirm({
        "move_1m_pct": -1.84,
        "move_3m_pct": 6.35,
        "move_5m_pct": 5.69,
        "acceleration": 5.0,
        "spread_pct": 0.23,
        "volume_ratio": 1.05,
        "score": 65,
    })

    assert result["confirmed"] is True
    assert result["points"] >= 6
