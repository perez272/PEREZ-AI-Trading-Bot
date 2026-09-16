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


def record_event(trade: dict, event: str, *, ts: str | None = None, **extra) -> str:
    """Append one immutable lifecycle event and return its UTC timestamp."""
    utc_ts = ts or now_utc()
    payload = {
        "ts_utc": utc_ts,
        "ts_ist": datetime.fromisoformat(utc_ts.replace("Z", "+00:00")).astimezone(IST).isoformat(timespec="milliseconds"),
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
    return utc_ts


def elapsed_seconds(start_ts: str | None, end_ts: str | None) -> float | None:
    if not start_ts or not end_ts:
        return None
    try:
        start = datetime.fromisoformat(str(start_ts).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end_ts).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return round(max(0.0, (end - start).total_seconds()), 3)
    except (TypeError, ValueError):
        return None
