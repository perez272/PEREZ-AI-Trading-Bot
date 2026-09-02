from pathlib import Path

from src.trading_risk_manager import TradingRiskManager


def manager(tmp_path: Path):
    return TradingRiskManager(
        state_file=str(tmp_path / "risk.json"),
        trailing_stop_pct=15.0,
        max_sl_triggers_per_lineage=2,
        max_consecutive_losses=3,
        circuit_breaker_hours=2,
    )


def test_trailing_stop_moves_only_up(tmp_path):
    rm = manager(tmp_path)

    rm.register_entry("T1", 100)

    stop, hit = rm.update_trailing_stop("T1", 100)
    assert stop is None
    assert hit is False

    stop, hit = rm.update_trailing_stop("T1", 200)
    assert stop == 170
    assert hit is False

    stop, hit = rm.update_trailing_stop("T1", 180)
    assert stop == 170
    assert hit is False

    stop, hit = rm.update_trailing_stop("T1", 169)
    assert stop == 170
    assert hit is True


def test_maximum_two_sl_triggers(tmp_path):
    rm = manager(tmp_path)

    rm.register_entry("T1", 100)

    allowed, _ = rm.record_stop_loss("T1")
    assert allowed is True

    allowed, _ = rm.record_stop_loss("T1")
    assert allowed is False

    allowed, reason = rm.can_open_trade(
        "T2",
        lineage_id="T1",
    )

    assert allowed is False
    assert "SL_LIMIT" in reason or "CLOSED" in reason


def test_three_consecutive_losses_activate_breaker(tmp_path):
    rm = manager(tmp_path)

    for i in range(3):
        trade_id = f"T{i}"

        rm.register_entry(trade_id, 100)
        rm.record_trade_result(trade_id, -10)

    status = rm.status()

    assert status["consecutive_losses"] == 3
    assert status["circuit_breaker_active"] is True

    allowed, reason = rm.can_open_trade("NEW")

    assert allowed is False
    assert "CIRCUIT_BREAKER" in reason


def test_win_resets_consecutive_losses(tmp_path):
    rm = manager(tmp_path)

    rm.register_entry("T1", 100)
    rm.record_trade_result("T1", -10)

    rm.register_entry("T2", 100)
    rm.record_trade_result("T2", -10)

    rm.register_entry("T3", 100)
    rm.record_trade_result("T3", 20)

    assert rm.status()["consecutive_losses"] == 0
    assert rm.status()["circuit_breaker_active"] is False
