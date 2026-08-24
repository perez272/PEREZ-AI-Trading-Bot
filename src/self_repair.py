"""Safe operational health checks and bounded recovery for PEREZ AI.

This module deliberately does not contain trading logic and never places orders.
It checks the main service and local heartbeat, then optionally restarts only the
PEREZ AI service when recovery is enabled.
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
STARTUP_GRACE_SECONDS = float(os.getenv("PEREZ_HEALTH_STARTUP_GRACE_SECONDS", "15"))
ALLOW_RESTART = os.getenv("PEREZ_HEALTH_ALLOW_RESTART", "true").strip().lower() in {"1", "true", "yes", "on"}

# These are lifecycle states emitted by the bot while the service is healthy.
# A heartbeat is unhealthy because it is stale, missing, malformed, explicitly
# stopped, or owned by a different MainPID -- not merely because it is not
# literally the string "running".
HEALTHY_HEARTBEAT_STATES = {
    "starting", "waiting_entry_window", "capital_check", "capital_error",
    "blocked", "scanning", "scan_error", "scanned", "index_momentum_candidate",
    "discovery_error", "fundamental_reject", "index_fundamental_bypass",
    "creating_trade", "monitoring", "monitor_error", "trade_complete",
}


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", *args], text=True, capture_output=True, timeout=20, check=False)


def service_active() -> bool:
    return _systemctl("is-active", "--quiet", SERVICE).returncode == 0


def service_main_pid() -> int | None:
    result = _systemctl("show", "-p", "MainPID", "--value", SERVICE)
    if result.returncode != 0:
        return None
    try:
        pid = int(result.stdout.strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def heartbeat_data() -> dict | None:
    if not HEARTBEAT.exists():
        return None
    try:
        data = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def heartbeat_age(data: dict | None = None) -> float | None:
    data = heartbeat_data() if data is None else data
    if data is None:
        return None
    try:
        epoch = float(data["epoch"])
    except (ValueError, TypeError, KeyError):
        return None
    return max(0.0, time.time() - epoch)


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


def _pid_matches(heartbeat_pid: object, main_pid: int | None) -> bool:
    if main_pid is None:
        return True
    try:
        return int(heartbeat_pid) == main_pid
    except (TypeError, ValueError):
        return False


def run() -> int:
    active = service_active()
    data = heartbeat_data()
    age = heartbeat_age(data)
    heartbeat_status = data.get("status") if data else None
    heartbeat_pid = data.get("pid") if data else None
    main_pid = service_main_pid() if active else None

    # During a genuine systemd start, the application may not have published a
    # fresh heartbeat yet. Give it one bounded grace period. This is only for the
    # startup state; it must not turn a stale heartbeat into a healthy one.
    if active and heartbeat_status in {None, "stopped", "starting"}:
        time.sleep(max(0.0, STARTUP_GRACE_SECONDS))
        active = service_active()
        data = heartbeat_data()
        age = heartbeat_age(data)
        heartbeat_status = data.get("status") if data else None
        heartbeat_pid = data.get("pid") if data else None
        main_pid = service_main_pid() if active else None

    print(
        f"HEALTH_CHECK service={SERVICE} active={active} main_pid={main_pid} "
        f"heartbeat_status={heartbeat_status} heartbeat_pid={heartbeat_pid} "
        f"heartbeat_age={age if age is not None else 'missing'}"
    )

    if not active:
        return 0 if restart_main_service("main service inactive") else 1
    if age is None:
        return 0 if restart_main_service("heartbeat missing or invalid") else 1
    if age > MAX_HEARTBEAT_AGE:
        return 0 if restart_main_service(f"heartbeat stale ({age:.1f}s)") else 1
    if heartbeat_status == "stopped":
        return 0 if restart_main_service("heartbeat explicitly stopped") else 1
    if heartbeat_status not in HEALTHY_HEARTBEAT_STATES:
        return 0 if restart_main_service(f"unknown heartbeat status {heartbeat_status!r}") else 1
    if not _pid_matches(heartbeat_pid, main_pid):
        return 0 if restart_main_service(
            f"heartbeat pid {heartbeat_pid!r} does not match service MainPID {main_pid}"
        ) else 1

    print("HEALTH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
