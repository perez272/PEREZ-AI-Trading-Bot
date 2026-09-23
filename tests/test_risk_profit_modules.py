import logging
from datetime import datetime, timezone

import pytest

from src.dynamic_strike_selector import select_target_strike
from src.spread_checker import is_spread_safe
from src.time_stop import (
    TIME_STOP_EXIT,
    TRAIL_TO_BREAKEVEN,
    NO_ACTION,
    evaluate_time_stop,
)


def test_dynamic_strike_ce_one_itm():
    assert select_target_strike("NIFTY", 25123.0, "CE", itm_depth=1) == 25050.0


def test_dynamic_strike_pe_one_itm():
    assert select_target_strike("BANKNIFTY", 55149.0, "PE", itm_depth=1) == 55200.0


@pytest.mark.parametrize(
    ("symbol", "spot", "step", "expected"),
    [
        ("NIFTY", 25124.0, 50, 25100.0),
        ("FINNIFTY", 25126.0, 50, 25150.0),
        ("MIDCPNIFTY", 12337.0, 25, 12325.0),
        ("NIFTYNXT50", 56774.0, 50, 56750.0),
    ],
)
def test_dynamic_strike_steps(symbol, spot, step, expected):
    assert select_target_strike(symbol, spot, "CE", itm_depth=0) == expected


def test_dynamic_strike_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        select_target_strike("NIFTY", 0, "CE")
    with pytest.raises(ValueError):
        select_target_strike("UNKNOWN", 25000, "CE")
    with pytest.raises(ValueError):
        select_target_strike("NIFTY", 25000, "XX")
    with pytest.raises(ValueError):
        select_target_strike("NIFTY", 25000, "CE", itm_depth=-1)


def test_spread_safe_under_half_percent():
    quote = {"depth": {"buy": [{"price": 100.0}], "sell": [{"price": 100.4}]}}
    assert is_spread_safe(quote, max_spread_pct=0.5) is True


def test_spread_blocks_over_half_percent(caplog):
    quote = {"depth": {"buy": [{"price": 100.0}], "sell": [{"price": 100.6}]}}
    with caplog.at_level(logging.WARNING):
        assert is_spread_safe(quote, max_spread_pct=0.5) is False
    assert "TRADE_BLOCKED_SPREAD" in caplog.text


def test_spread_blocks_empty_book(caplog):
    quote = {"depth": {"buy": [], "sell": []}}
    with caplog.at_level(logging.WARNING):
        assert is_spread_safe(quote) is False
    assert "TRADE_BLOCKED_SPREAD" in caplog.text


def test_spread_blocks_zero_bid_or_ask(caplog):
    quote = {"depth": {"buy": [{"price": 0}], "sell": [{"price": 101.0}]}}
    with caplog.at_level(logging.WARNING):
        assert is_spread_safe(quote) is False
    assert "TRADE_BLOCKED_SPREAD" in caplog.text


def test_time_stop_no_action_before_limit():
    assert evaluate_time_stop(
        "2026-09-23T09:30:00+05:30",
        "2026-09-23T09:44:59+05:30",
        target1=105.0,
        current_price=102.0,
        entry_price=100.0,
    ) == NO_ACTION


def test_time_stop_trails_profitable_trade_after_limit():
    assert evaluate_time_stop(
        "2026-09-23T09:30:00+05:30",
        "2026-09-23T09:45:00+05:30",
        target1=105.0,
        current_price=102.0,
        entry_price=100.0,
    ) == TRAIL_TO_BREAKEVEN


def test_time_stop_exits_loss_or_flat_after_limit():
    for price in (100.0, 99.0):
        assert evaluate_time_stop(
            datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc),
            datetime(2026, 9, 23, 9, 45, tzinfo=timezone.utc),
            target1=105.0,
            current_price=price,
            entry_price=100.0,
        ) == TIME_STOP_EXIT


def test_time_stop_does_nothing_if_t1_already_reached():
    assert evaluate_time_stop(
        "2026-09-23T09:30:00+05:30",
        "2026-09-23T10:00:00+05:30",
        target1=105.0,
        current_price=106.0,
        entry_price=100.0,
        target1_reached=True,
    ) == NO_ACTION
