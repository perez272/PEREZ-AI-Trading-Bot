from src.trade_engine import create_trade


def test_create_trade_reuses_gate_approved_contract():
    resolved = {
        "status": "CONTRACT VALID",
        "contract": "NIFTY25AUG25000CE",
        "exchange": "NFO",
        "token": "12345",
        "expiry": "2026-08-27",
        "strike": 25000,
        "lotsize": 75,
        "ltp": 100.0,
        "affordability_score": 90.0,
    }

    trade = create_trade("NIFTY", 25000.0, "BUY CE", 50000.0, resolved=resolved)

    assert trade["status"] == "PAPER TRADE ACTIVE"
    assert trade["contract"] == resolved["contract"]
    assert trade["token"] == resolved["token"]
    assert trade["quantity"] == 450
    assert trade["investment"] == 45000.0
    assert trade["live_orders"] is False


def test_create_trade_rejects_invalid_resolved_contract():
    resolved = {
        "status": "CONTRACT VALID",
        "contract": "BROKEN",
        "exchange": "NFO",
        "token": "1",
        "expiry": "2026-08-27",
        "strike": 25000,
        "lotsize": 0,
        "ltp": 100.0,
    }

    trade = create_trade("NIFTY", 25000.0, "BUY CE", 50000.0, resolved=resolved)

    assert trade["status"] == "INVALID CONTRACT"
