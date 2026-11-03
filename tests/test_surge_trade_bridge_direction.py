from src.surge_trade_bridge import _underlying_direction_check


def test_missing_underlying_confirmation_fails_closed():
    assert _underlying_direction_check("CE", None) == (False, "UNDERLYING_CONFIRMATION_UNAVAILABLE")
    assert _underlying_direction_check("PE", None) == (False, "UNDERLYING_CONFIRMATION_UNAVAILABLE")


def test_underlying_direction_must_match_option_type():
    assert _underlying_direction_check("CE", 0.25) == (True, "UNDERLYING_CONFIRMED")
    assert _underlying_direction_check("PE", -0.25) == (True, "UNDERLYING_CONFIRMED")
    assert _underlying_direction_check("CE", -0.25) == (False, "UNDERLYING_NOT_CONFIRMED")
    assert _underlying_direction_check("PE", 0.25) == (False, "UNDERLYING_NOT_CONFIRMED")
