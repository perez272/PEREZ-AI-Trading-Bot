from src.surge_trade_gate import SurgeEvidence, validate_surge


def evidence(**overrides):
    data = dict(
        symbol="NIFTY",
        option_type="CE",
        instrument_key="NSE_FO|TEST",
        expiry="2026-09-29",
        strike=25000.0,
        ltp=100.0,
        bid=99.0,
        ask=100.0,
        volume=5000.0,
        oi=20000.0,
        iv=15.0,
        move_1m_pct=3.0,
        move_3m_pct=4.0,
        move_5m_pct=6.0,
        velocity=2.0,
        acceleration=1.0,
        volume_ratio=2.0,
        spread_pct=1.0,
        slippage_pct=0.5,
        detector_score=85.0,
    )
    data.update(overrides)
    return SurgeEvidence(**data)


def test_valid_surge_passes():
    result = validate_surge(evidence(), 150.0)
    assert result["eligible"] is True
    assert result["reasons"] == []


def test_premium_above_limit_rejected():
    result = validate_surge(evidence(ltp=150.01), 150.0)
    assert result["eligible"] is False
    assert "PREMIUM_ABOVE_LIMIT" in result["reasons"]


def test_spread_above_limit_rejected():
    result = validate_surge(evidence(spread_pct=1.51), 150.0)
    assert result["eligible"] is False
    assert "WIDE_SPREAD" in result["reasons"]


def test_slippage_above_limit_rejected():
    result = validate_surge(evidence(slippage_pct=1.01), 150.0)
    assert result["eligible"] is False
    assert "HIGH_SLIPPAGE" in result["reasons"]
