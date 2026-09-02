from src.low_latency_stack import LeadingSignalEngine, order_flow_imbalance


def test_order_flow_imbalance():
    assert order_flow_imbalance(75, 25) == 0.5
    assert order_flow_imbalance(0, 0) == 0.0


def test_leading_signal_is_non_trading():
    e = LeadingSignalEngine(window=5)
    assert e.update(100, 100, 100, 100) is None
    s = e.update(101, 900, 100, 500)
    assert s is not None
    assert s.side == "BULLISH_SURGE"
    assert s.imbalance > 0.35
