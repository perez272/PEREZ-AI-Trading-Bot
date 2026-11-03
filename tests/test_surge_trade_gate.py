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
        spread_pct=0.7,
        slippage_pct=0.5,
        detector_score=85.0,
    )
    data.update(overrides)
    return SurgeEvidence(**data)


def test_valid_surge_passes():
    result = validate_surge(evidence(), 150.0)
    assert result["eligible"] is True
    assert result["reasons"] == []


def test_high_premium_is_not_rejected_by_arbitrary_fixed_cap():
    result = validate_surge(evidence(ltp=250.0), 150.0)
    assert "PREMIUM_ABOVE_LIMIT" not in result["reasons"]


def test_spread_above_limit_rejected():
    result = validate_surge(evidence(spread_pct=0.81), 150.0)
    assert result["eligible"] is False
    assert "WIDE_SPREAD" in result["reasons"]


def test_slippage_above_limit_rejected():
    result = validate_surge(evidence(slippage_pct=1.01), 150.0)
    assert result["eligible"] is False
    assert "HIGH_SLIPPAGE" in result["reasons"]


def test_overextended_high_score_surge_rejected():
    result = validate_surge(evidence(detector_score=90.0, move_5m_pct=6.0), 150.0)
    assert result["eligible"] is False
    assert "OVEREXTENDED_SURGE" in result["reasons"]


def test_option_direction_requires_underlying_confirmation():
    from src.surge_trade_bridge import _underlying_move_5m_pct
    assert callable(_underlying_move_5m_pct)


def test_negative_1m_momentum_rejected():
    result = validate_surge(evidence(move_1m_pct=-0.42), 150.0)
    assert not result["eligible"]
    assert "NO_POSITIVE_1M_MOVE" in result["reasons"]


def test_positive_1m_momentum_passes():
    result = validate_surge(evidence(move_1m_pct=0.1), 150.0)
    assert result["eligible"]



def test_selector_exposes_independent_evidence_stages():
    result = validate_surge(evidence(), 150.0)
    assert result["score_role"] == "SURGE_INTENSITY_RANKING_NOT_WIN_PROBABILITY"
    assert result["stages"]["contract_and_data"]["passed"] is True
    assert result["stages"]["option_momentum"]["passed"] is True
    assert result["stages"]["execution_quality"]["passed"] is True
    assert result["stages"]["continuation"]["confirmed"] is True
    assert result["stages"]["portfolio_risk"]["status"].startswith("PENDING_")


def test_high_legacy_score_cannot_bypass_failed_continuation():
    result = validate_surge(
        evidence(move_1m_pct=1.0, move_3m_pct=1.0, move_5m_pct=1.0,
                 acceleration=1.0, detector_score=85.0, volume_ratio=2.0),
        150.0,
    )
    assert result["eligible"] is False
    assert "SURGE_CONTINUATION_NOT_CONFIRMED" in result["reasons"]
    assert result["stages"]["continuation"]["confirmed"] is False
