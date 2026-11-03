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


def test_learning_mode_never_bypasses_confirmation(monkeypatch):
    monkeypatch.setenv("PAPER_LEARNING_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("ORDERS_ENABLED", "false")
    result = confirm({
        "move_1m_pct": 0.2, "move_3m_pct": 0.4, "move_5m_pct": 0.6,
        "acceleration": 0.1, "spread_pct": 1.0, "volume_ratio": 1.0, "score": 40,
    })
    assert result["confirmed"] is False
    assert "PAPER_LEARNING_MODE_BYPASS" not in result["reasons"]


def test_learning_mode_allows_strong_confirmation(monkeypatch):
    monkeypatch.setenv("PAPER_LEARNING_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("ORDERS_ENABLED", "false")
    result = confirm({
        "move_1m_pct": 2.5, "move_3m_pct": 4.0, "move_5m_pct": 4.5,
        "acceleration": 3.0, "spread_pct": 0.5, "volume_ratio": 1.5, "score": 75,
    })
    assert result["confirmed"] is True
