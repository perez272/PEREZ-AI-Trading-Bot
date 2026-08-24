"""Build a rotating, optionable market universe without network calls.

The live scanner keeps the major indices/core symbols on every pass and rotates
through NSE F&O equities from the local Angel instrument master. Rotation keeps
coverage broad while respecting broker pacing and the five-minute candle model.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.optionable_universe import get_optionable_universe
from src.upgrade_config import SYMBOLS, SCAN_BATCH_SIZE

IST = ZoneInfo("Asia/Kolkata")


def build_scan_symbols() -> dict[str, tuple[str, str]]:
    """Return the symbols for this scan cycle.

    Core symbols are always scanned. F&O equities are added in deterministic
    rotating batches so a broad universe is covered over the session instead of
    permanently limiting discovery to a handful of names.
    """
    result = dict(SYMBOLS)
    if SCAN_BATCH_SIZE <= len(result):
        return result

    universe = get_optionable_universe()
    dynamic = []
    for name, item in universe.items():
        name = str(name).upper().strip()
        if not name or name in result:
            continue
        token = str(item.get("token", "")).strip()
        if token:
            dynamic.append((name, ("NSE", token)))
    dynamic.sort(key=lambda item: item[0])

    slots = max(0, SCAN_BATCH_SIZE - len(result))
    if not dynamic or slots == 0:
        return result

    # Rotate once per minute. Each batch is stable during its scan and changes
    # on the next minute, giving broad coverage without random omissions.
    minute_index = int(datetime.now(IST).timestamp() // 60)
    batch_count = (len(dynamic) + slots - 1) // slots
    start = (minute_index % batch_count) * slots
    selected = dynamic[start:start + slots]
    if len(selected) < slots:
        selected += dynamic[:slots - len(selected)]

    result.update(dict(selected))
    return result
