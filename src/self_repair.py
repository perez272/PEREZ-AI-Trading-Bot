"""Safe operational health checks and bounded recovery for PEREZ AI.

This module deliberately does not contain trading logic and never places orders.
It checks the main service and local heartbeat, then optionally restarts only the
PEREZ AI service when recovery is enabled.  All thresholds are configurable via
environment variables so the health layer cannot silently invent trading policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(os.getenv("PEREZ_BOT_ROOT", "/home/ubuntu/PEREZ-AI-Trading-Bot"))
HEARTBEAT = ROOT / "data" / "runtime" / "heartbeat.json"
SERVICE = os.getenv("PEREZ_MAIN_SERVICE", "perez-ai.service")
MAX_HEARTBEAT_AGE = float(os.getenv("PEREZ_HEALTH_MAX_HEARTBEAT_AGE", "180"))
ALLOW_RESTART = os.getenv("PEREZ_HEALTH_ALLOW_RESTART", "true").strip().lower() in {
    "1", "true", "yes", "on"
}


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", *args],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def service_active() -> bool:
    return _systemctl("is-active", "--quiet", SERVICE).returncode == 0


def heartbeat_age() -> float | None:
    if not HEARTBEAT.exists():
        return None
    try:
        data = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        epoch = float(data["epoch"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    age = time.time() - epoch
    return max(0.0, age)


def restart_main_service(reason: str) -> bool:
    if not ALLOW_RESTART:
        print(f"HEALTH_DEGRADED: {reason}; automatic restart disabled")
        return False
    result = _systemctl("restart", SERVICE)
    if result.returncode == 0:
        print(f"HEALTH_RECOVERY: restarted {SERVICE}; reason={reason}")
        return True
    detail = (result.stderr or result.stdout).strip()
    print(f"HEALTH_RECOVERY_FAILED: {SERVICE}; reason={reason}; detail={detail}")
    return False


def run() -> int:
    active = service_active()
    age = heartbeat_age()
    print(
        f"HEALTH_CHECK service={SERVICE} active={active} "
        f"heartbeat_age={age if age is not None else 'missing'}"
    )

    if not active:
        return 0 if restart_main_service("main service inactive") else 1

    if age is None:
        return 0 if restart_main_service("heartbeat missing or invalid") else 1

    if age > MAX_HEARTBEAT_AGE:
        return 0 if restart_main_service(f"heartbeat stale ({age:.1f}s)") else 1

    print("HEALTH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
