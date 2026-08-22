from src.options_surge_engine import _expiry_bucket
from src.upgrade_config import FAST_SURGE_MODE, FAST_SURGE_SCAN_SECONDS, RESCAN_DELAY_SECONDS


def test_fast_surge_mode_is_enabled_and_bounded():
    assert FAST_SURGE_MODE is True
    assert FAST_SURGE_SCAN_SECONDS == 30
    assert RESCAN_DELAY_SECONDS == 30


def test_expiry_bucket_still_classifies_future_contracts():
    from datetime import datetime, timedelta

    expiry = (datetime.now().date() + timedelta(days=1)).isoformat()
    assert _expiry_bucket(expiry) == "EXPIRY_MINUS_1"
