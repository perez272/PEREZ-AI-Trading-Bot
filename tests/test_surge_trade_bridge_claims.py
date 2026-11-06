from src import surge_trade_bridge as bridge


def test_evaluation_exception_releases_event_claim(monkeypatch):
    released = []
    monkeypatch.setattr(bridge, "_claim_event", lambda event_id: True)
    monkeypatch.setattr(bridge, "_release_event", released.append)

    def fail_evaluation(_event):
        raise RuntimeError("temporary Upstox failure")

    monkeypatch.setattr(bridge, "evaluate_pending_surge", fail_evaluation)

    try:
        bridge.create_surge_trade({"id": 123}, 5000, object())
    except RuntimeError as exc:
        assert str(exc) == "temporary Upstox failure"
    else:
        raise AssertionError("Expected evaluation exception")

    assert released == [123]


def test_already_claimed_event_is_not_released(monkeypatch):
    released = []
    monkeypatch.setattr(bridge, "_claim_event", lambda event_id: False)
    monkeypatch.setattr(bridge, "_release_event", released.append)

    trade, result = bridge.create_surge_trade({"id": 456}, 5000, object())

    assert trade is None
    assert result["reason"] == "EVENT_ALREADY_CLAIMED"
    assert released == []
