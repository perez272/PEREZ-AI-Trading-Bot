from datetime import date, timedelta

from src.expiry_learning_engine import expiry_bucket
from src.options_surge_engine import _expiry_bucket


def test_expiry_buckets():
    today = date.today()
    assert expiry_bucket(today.isoformat(), today) == "EXPIRY_DAY"
    tomorrow = today + timedelta(days=1)
    assert expiry_bucket(tomorrow.isoformat(), today) == "EXPIRY_MINUS_1"


def test_internal_expiry_classifier_is_consistent():
    today = date.today()
    assert _expiry_bucket(today.isoformat()) == "EXPIRY_DAY"
