from src.safe_observation import SafeObservationEngine


def test_observes_every_5_seconds_without_refreshing_every_observation():
    engine = SafeObservationEngine(cadence_seconds=5, refresh_interval_seconds=60)
    calls = []

    def loader():
        calls.append(1)
        return {"close": 100}, "upstox"

    valid = lambda value: isinstance(value, dict) and value.get("close", 0) > 0

    first = engine.observe("NIFTY", loader, valid, now=0)
    second = engine.observe("NIFTY", loader, valid, now=5)
    third = engine.observe("NIFTY", loader, valid, now=59)
    fourth = engine.observe("NIFTY", loader, valid, now=60)

    assert first.data["close"] == 100
    assert second.observed_at == 5
    assert third.observed_at == 59
    assert fourth.refreshed_at == 60
    assert len(calls) == 2
    assert engine.stats["cache_hits"] == 2
    assert engine.stats["refresh_successes"] == 2


def test_failed_refresh_keeps_last_valid_snapshot_until_hard_age():
    engine = SafeObservationEngine(cadence_seconds=5, refresh_interval_seconds=10, max_snapshot_age_seconds=30)
    state = {"fail": False}

    def loader():
        if state["fail"]:
            raise RuntimeError("rate limited")
        return {"close": 100}, "angel_one"

    valid = lambda value: isinstance(value, dict) and value.get("close", 0) > 0

    first = engine.observe("BANKNIFTY", loader, valid, now=0)
    state["fail"] = True
    fallback = engine.observe("BANKNIFTY", loader, valid, now=10)
    expired = engine.observe("BANKNIFTY", loader, valid, now=31)

    assert first.data["close"] == 100
    assert fallback.data["close"] == 100
    assert fallback.source == "angel_one"
    assert expired is None
    assert engine.stats["refresh_failures"] == 2
    assert engine.stats["expired_snapshots"] == 1


def test_invalid_refresh_does_not_replace_valid_data():
    engine = SafeObservationEngine(refresh_interval_seconds=10)
    values = [({"close": 100}, "upstox"), ({"close": 0}, "upstox")]

    def loader():
        return values.pop(0)

    valid = lambda value: isinstance(value, dict) and value.get("close", 0) > 0

    first = engine.observe("RELIANCE", loader, valid, now=0)
    second = engine.observe("RELIANCE", loader, valid, now=10)

    assert first.data["close"] == 100
    assert second.data["close"] == 100
    assert second.refreshed_at == 0
    assert engine.stats["refresh_failures"] == 1
