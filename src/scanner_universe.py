"""Hard allowlist for PEREZ AI's Tier-1 index F&O scanner.

The scanner deliberately does NOT expand into individual equity F&O names.
NIFTYNXT50 and NIFTYFPI tokens are resolved from the local instrument master
when available so the policy remains symbol-based rather than token-fragile.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.upgrade_config import SYMBOLS, TIER1_INDEX_SYMBOLS

INSTRUMENT_FILE = Path("data/instruments.json")


def _index_tokens_from_master() -> dict[str, tuple[str, str]]:
    if not INSTRUMENT_FILE.exists():
        return {}
    try:
        data = json.loads(INSTRUMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    resolved: dict[str, tuple[str, str]] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        exchange = str(item.get("exch_seg", "")).upper().strip()
        if exchange != "NSE":
            continue
        token = str(item.get("token", "")).strip()
        symbol = str(item.get("symbol", "")).strip().upper()
        name = str(item.get("name", "")).strip().upper()
        for tier_symbol in TIER1_INDEX_SYMBOLS:
            if tier_symbol in resolved:
                continue
            if symbol == tier_symbol or name == tier_symbol:
                if token:
                    resolved[tier_symbol] = ("NSE", token)
    return resolved


def build_scan_symbols() -> dict[str, tuple[str, str]]:
    """Return ONLY the six configured Tier-1 index underlyings.

    This is a hard scanner-level allowlist. The function never calls the
    equity/F&O universe builder and never rotates through individual stocks.
    """
    resolved = _index_tokens_from_master()
    result: dict[str, tuple[str, str]] = {}

    for symbol in TIER1_INDEX_SYMBOLS:
        configured = SYMBOLS.get(symbol)
        if configured:
            result[symbol] = configured
        elif symbol in resolved:
            result[symbol] = resolved[symbol]

    # Prefer current instrument-master tokens when available for every index.
    result.update({symbol: resolved[symbol] for symbol in TIER1_INDEX_SYMBOLS if symbol in resolved})
    return result
