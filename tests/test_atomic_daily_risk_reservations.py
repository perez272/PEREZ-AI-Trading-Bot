import threading

import src.active_position_guard as guard
import src.risk_manager as risk


def _payload(risk_inr):
    return {"capital_available": 5000, "position_risk_inr": risk_inr}


def test_concurrent_claims_cannot_overreserve_daily_risk(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "DB", str(tmp_path / "runtime" / "active.sqlite3"))
    monkeypatch.setattr(risk, "daily_summary", lambda: {"pnl": 0.0})
    barrier = threading.Barrier(2)
    results = []

    def claim(contract, trade_id):
        barrier.wait()
        results.append(guard.claim_contract(
            contract, "NIFTY", trade_id, _payload(60.0)
        ))

    threads = [
        threading.Thread(target=claim, args=("NIFTY-CE-A", "trade-a")),
        threading.Thread(target=claim, args=("NIFTY-CE-B", "trade-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(ok for ok, _ in results) == 1
    assert sum("DAILY_RISK_BUDGET_EXCEEDED" in reason for _, reason in results) == 1


def test_realized_loss_reduces_remaining_reservation_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "DB", str(tmp_path / "runtime" / "active.sqlite3"))
    monkeypatch.setattr(risk, "daily_summary", lambda: {"pnl": -60.0})

    ok, reason = guard.claim_contract("NIFTY-CE-A", "NIFTY", "trade-a", _payload(50))
    assert not ok
    assert reason.startswith("DAILY_RISK_BUDGET_EXCEEDED")


def test_released_position_frees_only_its_open_risk_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "DB", str(tmp_path / "runtime" / "active.sqlite3"))
    monkeypatch.setattr(risk, "daily_summary", lambda: {"pnl": -50.0})

    ok, reason = guard.claim_contract("NIFTY-CE-A", "NIFTY", "trade-a", _payload(50))
    assert ok, reason
    guard.release_contract("NIFTY-CE-A", "trade-a")

    ok, reason = guard.claim_contract("NIFTY-PE-B", "NIFTY", "trade-b", _payload(50))
    assert ok, reason


def test_missing_risk_payload_fails_closed(tmp_path):
    monkeypatch_path = str(tmp_path / "runtime" / "active.sqlite3")
    original = guard.DB
    guard.DB = monkeypatch_path
    try:
        ok, reason = guard.claim_contract("NIFTY-CE-A", "NIFTY", "trade-a", {
            "capital_available": 5000
        })
        assert not ok
        assert reason == "RISK_RESERVATION_INVALID"
    finally:
        guard.DB = original
