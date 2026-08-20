"""Production safety primitives for the paper-trading process."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - EC2/Linux uses fcntl
    fcntl = None

STATE_DIR = Path("data/runtime")
LOCK_PATH = STATE_DIR / "perez_ai.lock"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"


def acquire_single_instance():
    """Hold an advisory process lock for the lifetime of the bot."""
    if fcntl is None:
        raise RuntimeError("Single-instance locking requires a POSIX host")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("Another PEREZ AI process is already running") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def release_single_instance(handle):
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def write_heartbeat(status="running", **extra):
    """Write a machine-readable heartbeat and optionally mirror it remotely."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "pid": os.getpid(),
        "status": status,
        **extra,
    }
    temp = HEARTBEAT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temp.replace(HEARTBEAT_PATH)

    # Remote publishing is deliberately best-effort. A cloud/API outage must
    # never stop the local scanner or paper-trading process.
    try:
        from src.remote_status import publish
        publish("heartbeat", payload)
    except Exception as exc:  # pragma: no cover - defensive production guard
        print(f"Remote heartbeat publish failed (non-fatal): {exc}")
    return payload
