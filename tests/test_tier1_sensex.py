from src.tier1_option_observer import TIER1_SYMBOLS


def test_sensex_is_in_tier1_observation_universe():
    assert "SENSEX" in TIER1_SYMBOLS
