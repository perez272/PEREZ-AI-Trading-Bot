"""
PEREZ AI — Hidden Value Data Layer
Read-only. No orders.
"""

import json
from pathlib import Path
from urllib.request import Request, urlopen


def load_instruments():
    path = Path("data/instruments.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def fetch_json(url, timeout=10):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_symbol_candidates():
    instruments = load_instruments()
    symbols = set()

    for item in instruments:
        symbol = str(item.get("symbol", "")).strip().upper()
        exchange = str(item.get("exch_seg", "")).upper()

        if symbol and exchange == "NSE":
            symbols.add(symbol)

    return sorted(symbols)


if __name__ == "__main__":
    symbols = get_symbol_candidates()

    print("=" * 60)
    print("PEREZ AI — HIDDEN VALUE DATA LAYER")
    print("=" * 60)
    print(f"NSE instruments available: {len(symbols)}")
    print("Orders enabled: FALSE")
    print("Mode: READ ONLY")
    print("=" * 60)
