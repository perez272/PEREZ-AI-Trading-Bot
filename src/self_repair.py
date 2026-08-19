"""PEREZ AI self-healing runtime guard.

This module is intentionally conservative: it can restart only the known
PEREZ services, never enables live orders, and never modifies source code.
Its job is process/service recovery, not autonomous code generation.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

SERVICES = (
    "perez-ai-bot.service",
    "perez-paper-monitor.service",
)
HEARTBEAT = Path(os.getenv("PEREZ_HEARTBEAT_FILE", "data/runtime/main_heartbeat"))
MAX_HEARTBEAT_AGE_SECONDS = int(os.getenv("PEREZ_HEARTBEAT_MAX_AGE", "900"))


def _active(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _restart(service: str) -> None:
    print(f"[SELF-REPAIR] Restarting {service}", flush=True)
    subprocess.run(["systemctl", "restart", service], check=False)


def _heartbeat_stale() -> bool:
    if not HEARTBEAT.exists():
        return True
    try:
        age = time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        return True
    return age > MAX_HEARTBEAT_AGE_SECONDS


def check_and_repair() -> int:
    repaired = False

    for service in SERVICES:
        if not _active(service):
            _restart(service)
            repaired = True

    # A stale heartbeat means the main scanner may be hung even though systemd
    # still sees the process as active. Only restart the main bot in this case.
    if _active("perez-ai-bot.service") and _heartbeat_stale():
        print("[SELF-REPAIR] Main heartbeat is stale; restarting scanner service", flush=True)
        _restart("perez-ai-bot.service")
        repaired = True

    if repaired:
        print("[SELF-REPAIR] Recovery actions completed", flush=True)
    else:
        print("[SELF-REPAIR] All monitored services healthy", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(check_and_repair())
