"""Build the NSE equity universe that has listed F&O contracts.

The Angel One instrument master is generated locally by src.instruments and is
not committed to GitHub.  This module reads that local file and never performs
network I/O at import time.
"""

import json
from pathlib import Path
from typing import Dict


INSTRUMENT_FILE = Path("data/instruments.json")


def _load_instruments():
    if not INSTRUMENT_FILE.exists():
        return []

    try:
        with INSTRUMENT_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def get_optionable_universe() -> Dict[str, dict]:
    """Return NSE EQ symbols whose underlying has NFO derivative contracts.

    Result format matches market_scanner_v3 expectations:
        {
            "RELIANCE": {
                "name": "RELIANCE",
                "symbol": "RELIANCE-EQ",
                "token": "2885",
                "exchange": "NSE",
            },
            ...
        }

    An empty dictionary is returned when the instrument master is unavailable;
    callers can then report an empty/unavailable universe without crashing.
    """
    instruments = _load_instruments()
    if not instruments:
        return {}

    optionable_names = set()
    for item in instruments:
        if not isinstance(item, dict):
            continue
        if str(item.get("exch_seg", "")).upper() != "NFO":
            continue
        name = str(item.get("name", "")).strip().upper()
        if name:
            optionable_names.add(name)

    universe: Dict[str, dict] = {}
    for item in instruments:
        if not isinstance(item, dict):
            continue
        if str(item.get("exch_seg", "")).upper() != "NSE":
            continue

        instrument_type = str(item.get("instrumenttype", "")).upper()
        symbol = str(item.get("symbol", "")).strip()
        name = str(item.get("name", "")).strip().upper()
        token = str(item.get("token", "")).strip()

        if not symbol.endswith("-EQ"):
            continue
        if instrument_type not in {"EQ", ""}:
            continue
        if not name or name not in optionable_names or not token:
            continue

        universe[name] = {
            "name": name,
            "symbol": symbol,
            "token": token,
            "exchange": "NSE",
        }

    return universe
