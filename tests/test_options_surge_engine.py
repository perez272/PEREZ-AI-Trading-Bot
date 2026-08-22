from datetime import date

from src.expiry_learning_engine import expiry_bucket
from src.options_surge_engine import _expiry_bucket


def test_expiry_buckets():
    today = date.today()
    assert expiry_bucket(today.isoformat(), today) == "EXPIRY_DAY"
    assert expiry_bucket((today.replace(day=today.day + 1)).isoformat(), today) == "EXPIRY_MINUS_1"


def test_internal_expiry_classifier_is_consistent():
    today = date.today()
    assert _expiry_bucket(today.isoformat()) == "EXPIRY_DAY"
