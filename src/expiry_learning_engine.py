"""Expiry-aware learning for options surge events.

Separates normal sessions, expiry-2, expiry-1 and expiry-day evidence. It
never turns an expiry event into a trade by itself; it produces historical
context for the existing ensemble/risk gates.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from src.options_surge_engine import _connect


def _parse_expiry(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def expiry_bucket(expiry: Any, today: Optional[date] = None) -> str:
    exp = _parse_expiry(expiry)
    if not exp:
        return "UNKNOWN"
    today = today or datetime.now().date()
    days = (exp - today).days
    if days == 0:
        return "EXPIRY_DAY"
    if days == 1:
        return "EXPIRY_MINUS_1"
    if days == 2:
        return "EXPIRY_MINUS_2"
    if days > 2:
        return "NORMAL"
    return "POST_EXPIRY"


def annotate_event(event: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    event = dict(event)
    event["expiry_bucket"] = expiry_bucket(event.get("expiry"), today)
    return event


def learn_from_surge(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return evidence for a surge profile; no execution authority."""
    event = annotate_event(event)
    bucket = event["expiry_bucket"]
    with _connect() as conn:
        rows = conn.execute(
            "SELECT change_pct, window_minutes, threshold_pct, features_json "
            "FROM option_surge_events WHERE expiry_bucket=? ORDER BY id DESC LIMIT 500",
            (bucket,),
        ).fetchall()
    count = len(rows)
    matching = [r for r in rows if int(r["window_minutes"]) == int(event["window_minutes"])]
    avg_move = (sum(float(r["change_pct"]) for r in matching) / len(matching)) if matching else 0.0
    return {
        "expiry_bucket": bucket,
        "samples": count,
        "same_window_samples": len(matching),
        "average_surge_pct": round(avg_move, 2),
        "focus": "EXPIRY_MINUS_1" if bucket == "EXPIRY_MINUS_1" else "GENERAL",
        "suggestion": (
            "Expiry-minus-1 pattern detected: require continuation confirmation and tight spread/liquidity before considering a setup."
            if bucket == "EXPIRY_MINUS_1"
            else "Use normal regime/ensemble evidence; do not chase a surge solely because premium rose."
        ),
    }


def expiry_learning_summary() -> Dict[str, Dict[str, float]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT expiry_bucket, COUNT(*) n, AVG(change_pct) avg_change "
            "FROM option_surge_events GROUP BY expiry_bucket"
        ).fetchall()
    return {
        str(r["expiry_bucket"]): {"events": int(r["n"]), "avg_change_pct": round(float(r["avg_change"] or 0), 2)}
        for r in rows
    }
