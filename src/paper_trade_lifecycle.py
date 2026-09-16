"""Canonical paper-trade lifecycle telemetry.

Records detection/open/partial/final-close events with timezone-aware timestamps.
Telemetry only: it never changes entry, risk, or order behavior.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LIFECYCLE_LOG = Path("data/paper_trade_lifecycle.jsonl")
IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def now_ist() -> str:
    return datetime.now(IST).isoformat(timespec="milliseconds")


def _aware(raw: str) -> datetime:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def record_event(trade: dict, event: str, *, ts: str | None = None, **extra) -> str:
    """Append one immutable lifecycle event and return its UTC timestamp."""
    utc_ts = ts or now_utc()
    instant = _aware(utc_ts).astimezone(timezone.utc)
    payload = {
        "ts_utc": instant.isoformat(timespec="milliseconds"),
        "ts_ist": instant.astimezone(IST).isoformat(timespec="milliseconds"),
        "event": str(event),
        "trade_id": str(trade.get("trade_id") or ""),
        "lineage_id": str(trade.get("lineage_id") or trade.get("trade_id") or ""),
        "symbol": str(trade.get("symbol") or ""),
        "contract": str(trade.get("contract") or ""),
        "strategy": str(trade.get("strategy") or "CORE"),
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value

    LIFECYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LIFECYCLE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    return instant.isoformat(timespec="milliseconds")


def elapsed_seconds(start_ts: str | None, end_ts: str | None) -> float | None:
    if not start_ts or not end_ts:
        return None
    try:
        start = _aware(start_ts)
        end = _aware(end_ts)
        return round(max(0.0, (end - start).total_seconds()), 3)
    except (TypeError, ValueError):
        return None
