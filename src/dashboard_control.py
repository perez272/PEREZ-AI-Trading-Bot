"""Safe control-plane state shared by the dashboard and trading workers.

Controls never enable live orders and never change risk parameters.  The
trading engine treats a missing/corrupt control file as fail-safe: new entries
remain allowed unless an explicit stop/emergency flag is present.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "dashboard_control.json"
AUDIT_PATH = ROOT / "data" / "dashboard_actions.jsonl"
_LOCK = threading.Lock()

DEFAULTS = {
    "new_entries_enabled": True,
    "scanner_enabled": True,
    "observer_enabled": True,
    "emergency_mode": False,
}


def _now():
    return datetime.now(IST).isoformat(timespec="seconds")


def _read():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("control state is not an object")
    except Exception:
        data = {}
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            out[key] = bool(data[key])
    out["updated_at"] = data.get("updated_at", None)
    return out


def get_state():
    return _read()


def set_controls(changes: dict, action: str, reason: str = ""):
    allowed = set(DEFAULTS)
    with _LOCK:
        before = _read()
        after = dict(before)
        for key, value in changes.items():
            if key in allowed:
                after[key] = bool(value)
        after["updated_at"] = _now()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, STATE_PATH)
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "time_ist": _now(),
            "action": action,
            "reason": reason[:500],
            "before": {k: before[k] for k in DEFAULTS},
            "after": {k: after[k] for k in DEFAULTS},
            "result": "APPLIED",
        }
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return after


def entries_allowed():
    s = _read()
    return s["new_entries_enabled"] and not s["emergency_mode"]


def scanner_allowed():
    s = _read()
    return s["scanner_enabled"] and not s["emergency_mode"]


def observer_allowed():
    s = _read()
    return s["observer_enabled"] and not s["emergency_mode"]


def append_audit(action: str, reason: str = "", target: str = "", result: str = "RECORDED", details=None):
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time_ist": _now(), "action": action, "target": target,
        "reason": reason[:500], "result": result,
    }
    if details is not None:
        record["details"] = details
    with _LOCK:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def recent_audit(limit: int = 50):
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []
