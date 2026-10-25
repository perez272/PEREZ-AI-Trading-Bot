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


def test_breakeven_does_not_count_as_loss(tmp_path):
    rm = manager(tmp_path)

    rm.register_entry("T1", 100)
    rm.record_trade_result("T1", 0)

    assert rm.status()["consecutive_losses"] == 0
    assert rm.status()["circuit_breaker_active"] is False


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


def test_duplicate_loss_result_counts_once(tmp_path):
    rm = manager(tmp_path)
    rm.register_entry("LINEAGE-1", 100)

    assert rm.record_trade_result("LINEAGE-1", -10, result_id="TRADE-1") is True
    assert rm.record_trade_result("LINEAGE-1", -10, result_id="TRADE-1") is False
    assert rm.status()["consecutive_losses"] == 1


def test_duplicate_old_win_cannot_reset_newer_loss(tmp_path):
    rm = manager(tmp_path)
    rm.record_trade_result("LINEAGE-1", 20, result_id="TRADE-WIN")
    rm.record_trade_result("LINEAGE-2", -10, result_id="TRADE-LOSS")

    assert rm.record_trade_result("LINEAGE-1", 20, result_id="TRADE-WIN") is False
    assert rm.status()["consecutive_losses"] == 1


def test_result_deduplication_survives_reload(tmp_path):
    rm = manager(tmp_path)
    rm.record_trade_result("LINEAGE-1", -10, result_id="TRADE-1")

    reloaded = manager(tmp_path)
    assert reloaded.record_trade_result("LINEAGE-1", -10, result_id="TRADE-1") is False
    assert reloaded.status()["consecutive_losses"] == 1


def test_distinct_trades_in_same_lineage_count_separately(tmp_path):
    rm = manager(tmp_path)
    rm.register_entry("LINEAGE-1", 100)

    assert rm.record_trade_result("LINEAGE-1", -10, stop_loss=True, result_id="TRADE-1") is True
    rm.register_entry("TRADE-2", 100, lineage_id="LINEAGE-1")
    assert rm.record_trade_result("LINEAGE-1", -10, stop_loss=True, result_id="TRADE-2") is True

    assert rm.status()["consecutive_losses"] == 2
    assert rm.positions["LINEAGE-1"].sl_triggers == 2
    assert rm.positions["LINEAGE-1"].active is False


def test_result_persistence_failure_rolls_back_and_allows_retry(tmp_path, monkeypatch):
    rm = manager(tmp_path)
    rm.register_entry("LINEAGE-1", 100)
    original_save = rm._save_state

    def fail_save():
        raise OSError("simulated disk failure")

    monkeypatch.setattr(rm, "_save_state", fail_save)
    try:
        rm.record_trade_result("LINEAGE-1", -10, result_id="TRADE-FAIL")
    except OSError:
        pass
    else:
        raise AssertionError("expected simulated persistence failure")

    assert "TRADE-FAIL" not in rm.processed_result_ids
    assert rm.status()["consecutive_losses"] == 0

    monkeypatch.setattr(rm, "_save_state", original_save)
    assert rm.record_trade_result("LINEAGE-1", -10, result_id="TRADE-FAIL") is True
    assert rm.status()["consecutive_losses"] == 1


def test_stop_loss_results_enforce_lineage_reentry_limit(tmp_path):
    rm = manager(tmp_path)
    rm.register_entry("LINEAGE-1", 100)

    assert rm.record_trade_result(
        "LINEAGE-1", -10, stop_loss=True, result_id="TRADE-1"
    ) is True
    assert rm.positions["LINEAGE-1"].sl_triggers == 1
    assert rm.positions["LINEAGE-1"].active is True

    rm.register_entry("TRADE-2", 100, lineage_id="LINEAGE-1")
    assert rm.record_trade_result(
        "LINEAGE-1", -10, stop_loss=True, result_id="TRADE-2"
    ) is True

    assert rm.positions["LINEAGE-1"].sl_triggers == 2
    assert rm.positions["LINEAGE-1"].active is False
    allowed, reason = rm.can_open_trade("TRADE-3", lineage_id="LINEAGE-1")
    assert allowed is False
    assert reason == "TRADE_LINEAGE_CLOSED"
