from src.options_trade_gate import OptionEvidence, validate_trade


def _valid(**overrides):
    values = dict(
        symbol="NIFTY",
        option_type="CE",
        expiry="25AUG2026",
        ltp=50.0,
        trend_score=10.0,
        momentum_score=7.0,
        volume_score=8.0,
        vwap_score=7.0,
        volatility_score=5.0,
        structure_score=5.0,
        oi_score=5.0,
        oi_change_score=8.0,
        iv_score=5.0,
        liquidity_score=7.0,
        index_confirmation=8.0,
        news_confirmation=5.0,
        avg_price=48.0,
        best_bid=49.8,
        best_ask=50.2,
        spread_pct=0.8,
        slippage_pct=0.4,
        underlying_signal="BUY CE",
        mtf_direction="BULLISH",
        percent_change=2.5,
        live_market_data=True,
    )
    values.update(overrides)
    return OptionEvidence(**values)


def test_bullish_ce_can_pass_with_independent_live_evidence():
    result = validate_trade(_valid())
    assert result["eligible"] is True


def test_bullish_market_cannot_authorize_put():
    result = validate_trade(_valid(option_type="PE", underlying_signal="BUY PE"))
    assert result["eligible"] is False
    assert "MTF_DIRECTION_MISMATCH" in result["reasons"]


def test_bearish_market_cannot_authorize_call():
    result = validate_trade(_valid(underlying_signal="BUY PE", mtf_direction="BEARISH"))
    assert result["eligible"] is False
    assert "OPTION_SIGNAL_MISMATCH" in result["reasons"]


def test_missing_live_order_book_is_rejected():
    result = validate_trade(_valid(best_bid=0.0, best_ask=0.0))
    assert result["eligible"] is False
    assert "INVALID_ORDER_BOOK" in result["reasons"]


def test_negative_option_momentum_is_rejected():
    result = validate_trade(_valid(percent_change=-1.0))
    assert result["eligible"] is False
    assert "NEGATIVE_OPTION_MOMENTUM" in result["reasons"]


def test_below_average_option_price_is_rejected():
    result = validate_trade(_valid(avg_price=51.0))
    assert result["eligible"] is False
    assert "BELOW_LIVE_AVERAGE_PRICE" in result["reasons"]


def test_missing_live_market_data_is_rejected():
    result = validate_trade(_valid(live_market_data=False))
    assert result["eligible"] is False
    assert "LIVE_OPTION_DATA_REQUIRED" in result["reasons"]
