from src.upgrade_config import PER_SYMBOL_DELAY_SECONDS, RESCAN_DELAY_SECONDS


def test_observation_cadence_is_five_seconds():
    assert RESCAN_DELAY_SECONDS == 5
    # Provider pacing belongs to the provider client, not the scanner loop.
    assert PER_SYMBOL_DELAY_SECONDS == 0
