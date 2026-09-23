from datetime import datetime

from src.hybrid_exit_engine import evaluate_hybrid_exit, is_expiry_day


def _position():
    return {
        "entry_price": 100.0,
        "hard_sl_price": 70.0,
        "target_1_price": 110.0,
        "highest_price_reached": 100.0,
        "trailing_sl_price": 70.0,
    }


def test_normal_day_fixed_target_exit():
    position = _position()
    action = evaluate_hybrid_exit(
        position, 110.0, datetime(2026, 9, 23), "NIFTY"
    )
    assert action == "EXIT_TARGET"


def test_normal_day_hard_stop_exit():
    position = _position()
    action = evaluate_hybrid_exit(
        position, 70.0, datetime(2026, 9, 23), "NIFTY"
    )
    assert action == "EXIT_STOP_LOSS"


def test_normal_day_holds_below_target():
    position = _position()
    action = evaluate_hybrid_exit(
        position, 105.0, datetime(2026, 9, 23), "NIFTY"
    )
    assert action == "HOLD"


def test_nifty_tuesday_is_expiry_day():
    assert is_expiry_day("NIFTY", datetime(2026, 9, 29)) is True


def test_nifty_wednesday_is_not_expiry_day():
    assert is_expiry_day("NIFTY", datetime(2026, 9, 30)) is False


def test_sensex_thursday_is_expiry_day():
    assert is_expiry_day("SENSEX", datetime(2026, 9, 24)) is True


def test_expiry_day_ignores_fixed_target_and_ratchets_trail(caplog):
    position = _position()

    with caplog.at_level("INFO"):
        action = evaluate_hybrid_exit(
            position, 116.0, datetime(2026, 9, 29), "NIFTY"
        )

    assert action == "HOLD"
    assert position["highest_price_reached"] == 116.0
    assert position["trailing_sl_price"] == 101.0
    assert "Expiry Day" in caplog.text

    action = evaluate_hybrid_exit(
        position, 130.0, datetime(2026, 9, 29), "NIFTY"
    )
    assert action == "HOLD"
    assert position["highest_price_reached"] == 130.0
    assert position["trailing_sl_price"] == 115.0

    action = evaluate_hybrid_exit(
        position, 114.0, datetime(2026, 9, 29), "NIFTY"
    )
    assert action == "EXIT_TRAIL"
    assert position["trailing_sl_price"] == 115.0


def test_expiry_day_before_15_point_profit_uses_hard_stop():
    position = _position()
    action = evaluate_hybrid_exit(
        position, 95.0, datetime(2026, 9, 29), "NIFTY"
    )
    assert action == "HOLD"
    assert position["highest_price_reached"] == 100.0
    assert position["trailing_sl_price"] == 70.0

    action = evaluate_hybrid_exit(
        position, 70.0, datetime(2026, 9, 29), "NIFTY"
    )
    assert action == "EXIT_STOP_LOSS"


def test_expiry_trailing_stop_never_ratchets_down():
    position = _position()
    evaluate_hybrid_exit(position, 125.0, datetime(2026, 9, 29), "NIFTY")
    assert position["trailing_sl_price"] == 110.0

    evaluate_hybrid_exit(position, 120.0, datetime(2026, 9, 29), "NIFTY")
    assert position["highest_price_reached"] == 125.0
    assert position["trailing_sl_price"] == 110.0
