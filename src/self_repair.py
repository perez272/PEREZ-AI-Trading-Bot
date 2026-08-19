"""PEREZ AI self-healing runtime guard.

Conservative service recovery only. During the configured off-hours window,
health checks must not restart the trading services that the daily scheduler
intentionally stopped.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from src.risk_manager import is_runtime_window

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
    # The daily scheduler intentionally stops trading services after market
    # close. Never undo that scheduled shutdown during off-hours/weekends.
    if not is_runtime_window():
        print("[SELF-REPAIR] Outside trading runtime window; scheduled services remain stopped.", flush=True)
        return 0

    repaired = False

    for service in SERVICES:
        if not _active(service):
            _restart(service)
            repaired = True

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
