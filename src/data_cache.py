import os
import pickle

from datetime import datetime, timedelta, timezone


CACHE_DIR = "data/cache"

os.makedirs(
    CACHE_DIR,
    exist_ok=True
)


def _utc_now():
    return datetime.now(timezone.utc)


def cache_file(symbol):
    return os.path.join(
        CACHE_DIR,
        f"{symbol}.pkl"
    )


def save_cache(symbol, data):
    try:
        with open(
            cache_file(symbol),
            "wb"
        ) as f:

            pickle.dump(
                {
                    "timestamp": _utc_now(),
                    "data": data,
                },
                f,
            )

        return True

    except Exception as e:
        print(
            "Cache save error:",
            e
        )
        return False


def load_cache(symbol):
    file = cache_file(symbol)

    if not os.path.exists(file):
        return None

    try:
        with open(
            file,
            "rb"
        ) as f:
            return pickle.load(f)

    except Exception:
        return None


def _normalize_timestamp(timestamp):
    """
    Convert old/new cache timestamps into
    timezone-aware UTC timestamps.
    """

    if not isinstance(timestamp, datetime):
        return None

    # Old cache files contain naive UTC timestamps.
    if timestamp.tzinfo is None:
        return timestamp.replace(
            tzinfo=timezone.utc
        )

    return timestamp.astimezone(
        timezone.utc
    )


def cache_age_minutes(symbol):
    obj = load_cache(symbol)

    if not obj:
        return None

    timestamp = _normalize_timestamp(
        obj.get("timestamp")
    )

    if timestamp is None:
        return None

    age = _utc_now() - timestamp

    return max(
        0.0,
        age.total_seconds() / 60.0
    )


def cache_valid(symbol, minutes=5):
    age = cache_age_minutes(symbol)

    if age is None:
        return False

    return age < minutes


def clear_cache(symbol):
    file = cache_file(symbol)

    if os.path.exists(file):
        os.remove(file)
