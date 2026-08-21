import pandas as pd

from src.ai_scoring import calculate_score, score_setup
from src.trade_decision import get_trade_decision


def _frame(**overrides):
    row = {
        "close": 105.0,
        "EMA20": 103.0,
        "EMA50": 100.0,
        "EMA200": 95.0,
        "MACD": 2.0,
        "MACD_SIGNAL": 1.0,
        "RSI": 60.0,
        "VWAP": 102.0,
        "volume_ratio": 1.6,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_score_is_backward_compatible_and_explainable():
    result = score_setup(_frame())
    assert 0 <= result["score"] <= 100
    assert result["bias"] == "BULLISH"
    assert result["confidence"] > 0
    assert "ema_stack" in result["components"]
    assert calculate_score(_frame()) == result["score"]


def test_conflicting_evidence_waits():
    decision, reason = get_trade_decision(
        score=65,
        rsi=60,
        ema20=103,
        ema50=100,
        ema200=110,
        close=105,
    )
    assert decision == "NO TRADE"
    assert reason == "INSUFFICIENT CONFLUENCE"


def test_high_conviction_bullish_setup():
    decision, reason = get_trade_decision(
        score=80,
        rsi=61,
        ema20=103,
        ema50=100,
        ema200=95,
        close=105,
        atr=2.0,
        previous_high=104,
        volume_ratio=1.6,
    )
    assert decision == "BUY CE"
    assert reason == "HIGH-CONVICTION BULLISH"


def test_overextended_breakout_requires_volume():
    decision, reason = get_trade_decision(
        score=80,
        rsi=75,
        ema20=103,
        ema50=100,
        ema200=95,
        close=106,
        previous_high=104,
        volume_ratio=1.0,
    )
    assert decision == "NO TRADE"
    assert reason == "BULLISH BUT OVEREXTENDED"
