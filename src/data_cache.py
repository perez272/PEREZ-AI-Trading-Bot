import os
import pickle
from datetime import datetime, timedelta

CACHE_DIR = "data/cache"

os.makedirs(CACHE_DIR, exist_ok=True)


def cache_file(symbol):
    return os.path.join(CACHE_DIR, f"{symbol}.pkl")


def save_cache(symbol, data):
    with open(cache_file(symbol), "wb") as f:
        pickle.dump(
            {
                "timestamp": datetime.now(),
                "data": data,
            },
            f,
        )


def load_cache(symbol):

    file = cache_file(symbol)

    if not os.path.exists(file):
        return None

    with open(file, "rb") as f:
        obj = pickle.load(f)

    return obj


def cache_valid(symbol, minutes=5):

    obj = load_cache(symbol)

    if obj is None:
        return False

    age = datetime.now() - obj["timestamp"]

    return age < timedelta(minutes=minutes)
