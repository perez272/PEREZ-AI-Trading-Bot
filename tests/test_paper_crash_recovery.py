import json
import threading
from pathlib import Path
from src import paper_position_recovery as recovery
from src import paper_trade_lifecycle as lifecycle

def payload():
    return {"trade_id":"recover-001","lineage_id":"lineage-001","symbol":"NIFTY",
            "contract":"NIFTY26NOV25000CE","signal":"BUY CE","exchange":"NFO",
            "token":"NSE_FO|test-token","entry":100.0,"quantity":25,
            "original_quantity":25,"remaining_quantity":25,"initial_stop_loss":90.0,
            "stop_loss":90.0,"target1":115.0,"target2":130.0,"target":130.0,
            "partial_booked":False,"realized_pnl":0.0,"opened_at":"2026-11-02T10:00:00+00:00",
            "status":"PAPER TRADE ACTIVE","live_orders":False,"strategy":"SURGE_EARLY_EXPLOSIVE"}

def row(p, status="ACTIVE"):
    return (p["contract"], p["symbol"], p["trade_id"], "2026-11-02T10:00:00+00:00",
            status, json.dumps(p))

def test_pending_claim_is_not_reconstructed():
    p = payload()
    assert recovery._reconstruct(row(p, "PENDING"), {}) is None

def test_active_claim_recovers_without_open_event():
    p = payload()
    trade = recovery._reconstruct(row(p), {})
    assert trade["trade_id"] == p["trade_id"] and trade["token"] == p["token"]
    assert trade["remaining_quantity"] == 25 and trade["live_orders"] is False

def test_recovery_uses_latest_partial_state():
    p = payload()
    events = {p["trade_id"]:[{"event":"TARGET1_PARTIAL","remaining_quantity":12,"realized_pnl":37.5}]}
    trade = recovery._reconstruct(row(p), events)
    assert trade["partial_booked"] and trade["remaining_quantity"] == 12
    assert trade["realized_pnl"] == 37.5

def test_close_event_prevents_reconstruction():
    p = payload()
    events = {p["trade_id"]:[{"event":"CLOSE","trade_id":p["trade_id"]}]}
    assert recovery._reconstruct(row(p), events) is None

def test_close_is_idempotent(tmp_path, monkeypatch):
    log = tmp_path / "events.jsonl"
    monkeypatch.setattr(lifecycle, "LIFECYCLE_LOG", log)
    monkeypatch.setattr(lifecycle, "_CLOSE_EVENT_LOCK", threading.Lock())
    trade = {"trade_id":"close-001","symbol":"NIFTY","contract":"NIFTY26NOV25000CE"}
    first = lifecycle.record_event(trade, "CLOSE", pnl=10)
    second = lifecycle.record_event(trade, "CLOSE", pnl=10)
    assert first == second and len(log.read_text().splitlines()) == 1

def test_closed_claim_replays_risk_result_before_release(monkeypatch):
    p = payload()
    close = {"event":"CLOSE","trade_id":p["trade_id"],"lineage_id":p["lineage_id"],
             "pnl":-22.5,"exit_reason":"STOP_LOSS"}
    released = []
    calls = []
    class FakeRiskManager:
        def record_trade_result(self, identity, pnl, *, stop_loss, result_id):
            calls.append((identity, pnl, stop_loss, result_id))
            return True
    from src import trading_risk_manager
    monkeypatch.setattr(trading_risk_manager, "TradingRiskManager", FakeRiskManager)
    monkeypatch.setattr(recovery, "active_contracts", lambda: [row(p)])
    monkeypatch.setattr(recovery, "_events", lambda: {p["trade_id"]:[close]})
    monkeypatch.setattr(recovery, "release_contract",
                        lambda contract, trade_id: released.append((contract, trade_id)))
    assert recovery.recover_paper_positions() == 0
    assert calls == [(p["lineage_id"], -22.5, True, p["trade_id"])]
    assert released == [(p["contract"], p["trade_id"])]
