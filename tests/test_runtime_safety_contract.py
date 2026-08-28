from src import upgrade_config


def test_option_and_entry_limits_match_paper_trading_policy():
    assert upgrade_config.OPTION_MAX_PREMIUM == 100.0
    assert upgrade_config.ENTRY_START.hour == 9
    assert upgrade_config.ENTRY_START.minute == 30
    assert upgrade_config.LAST_ENTRY.hour == 14
    assert upgrade_config.LAST_ENTRY.minute == 45
    assert upgrade_config.FORCED_EXIT_TIME.hour == 15
    assert upgrade_config.FORCED_EXIT_TIME.minute == 10


def test_risk_limits_remain_fail_safe():
    assert upgrade_config.MAX_TRADES_PER_DAY == 3
    assert upgrade_config.MAX_DAILY_DRAWDOWN_PCT == 2.0
    assert upgrade_config.MAX_SPREAD_PCT <= 1.5
    assert upgrade_config.MAX_SLIPPAGE_PCT <= 1.0
