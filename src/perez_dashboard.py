#!/usr/bin/env python3
"""Read-only live dashboard for PEREZ-AI-Trading-Bot.

No trading APIs are called and no bot/risk settings are modified.
Uses only Python stdlib so the dashboard adds no runtime dependency.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CORE_DB = ROOT / "data/memory/perez_ai_memory.db"
TIER_DB = ROOT / "data/memory/tier1_option_moves.sqlite3"
HTML = ROOT / "dashboard/index.html"
HOST = os.getenv("PEREZ_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("PEREZ_DASHBOARD_PORT", "8787"))


def db_query(path: Path, sql: str, params=()):
    if not path.exists():
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def db_scalar(path: Path, sql: str, params=(), default=0):
    rows = db_query(path, sql, params)
    if not rows:
        return default
    return next(iter(rows[0].values()), default)


def service_state(name: str) -> str:
    try:
        p = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=1)
        return p.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def env_flag(name: str, default: str = "") -> str:
    # Dashboard is deliberately conservative: inspect the environment of this process
    # only; do not parse or expose secrets from .env files.
    return os.getenv(name, default)


def latest(path: Path, table: str, columns: str, order: str = "id"):
    try:
        return db_query(path, f"SELECT {columns} FROM {table} ORDER BY {order} DESC LIMIT 1")
    except Exception:
        return []


def build_state():
    tier_counts = {}
    for table in ("observations", "move_events", "early_events", "raw_option_snapshots"):
        try:
            tier_counts[table] = int(db_scalar(TIER_DB, f"SELECT COUNT(*) FROM {table}"))
        except Exception:
            tier_counts[table] = 0

    core_counts = {}
    for table in ("observations", "rejections", "outcomes", "lessons"):
        try:
            core_counts[table] = int(db_scalar(CORE_DB, f"SELECT COUNT(*) FROM {table}"))
        except Exception:
            core_counts[table] = 0

    early = latest(TIER_DB, "early_events", "*", "id")
    moves = latest(TIER_DB, "move_events", "*", "id")
    outcomes = latest(CORE_DB, "outcomes", "*", "id")
    rejections = latest(CORE_DB, "rejections", "*", "id")

    open_outcomes = db_query(
        CORE_DB,
        "SELECT id,ts,symbol,signal,contract,score,pnl,pnl_percent,exit_reason,trade_id "
        "FROM outcomes ORDER BY id DESC LIMIT 20",
    )

    recent_rejections = db_query(
        CORE_DB,
        "SELECT id,ts,symbol,signal,score,options_score,reason FROM rejections ORDER BY id DESC LIMIT 20",
    )

    recent_early = db_query(
        TIER_DB,
        "SELECT id,observed_ts,symbol,instrument_key,expiry,strike,option_type,ltp,reason "
        "FROM early_events ORDER BY id DESC LIMIT 30",
    )

    recent_moves = db_query(
        TIER_DB,
        "SELECT id,observed_ts,symbol,contract,option_type,expiry,strike,window_minutes,threshold_pct,change_pct,start_ltp,end_ltp "
        "FROM move_events ORDER BY id DESC LIMIT 30",
    )

    services = {
        "perez-ai.service": service_state("perez-ai.service"),
        "perez-tier1-option-observer.service": service_state("perez-tier1-option-observer.service"),
        "perez-telegram-updater.service": service_state("perez-telegram-updater.service"),
    }

    disk = shutil.disk_usage(ROOT)
    state_file = ROOT / "data/runtime/learning_status.json"
    learning_status = {}
    if state_file.exists():
        try:
            learning_status = json.loads(state_file.read_text())
        except Exception:
            learning_status = {}

    return {
        "server_ts": datetime.now(timezone.utc).isoformat(),
        "project": str(ROOT),
        "mode": {
            "paper_mode": env_flag("PAPER_MODE", "unknown"),
            "orders_enabled": env_flag("ORDERS_ENABLED", "unknown"),
            "upstox_enabled": env_flag("UPSTOX_ENABLED", "unknown"),
            "provider": env_flag("MARKET_DATA_PROVIDER", "unknown"),
        },
        "services": services,
        "resources": {
            "disk_used_pct": round((disk.used / disk.total) * 100, 1),
            "disk_free_gb": round(disk.free / (1024**3), 2),
        },
        "counts": {"tier1": tier_counts, "core": core_counts},
        "latest": {"early_event": early[0] if early else None, "move_event": moves[0] if moves else None, "outcome": outcomes[0] if outcomes else None, "rejection": rejections[0] if rejections else None},
        "recent": {"early_events": recent_early, "move_events": recent_moves, "outcomes": open_outcomes, "rejections": recent_rejections},
        "learning_status": learning_status,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            try:
                self._send(200, "text/html; charset=utf-8", HTML.read_bytes())
            except Exception as exc:
                self._send(500, "text/plain; charset=utf-8", str(exc).encode())
            return
        if path == "/api/state":
            try:
                body = json.dumps(build_state(), default=str).encode()
                self._send(200, "application/json; charset=utf-8", body)
            except Exception as exc:
                self._send(500, "application/json; charset=utf-8", json.dumps({"error": str(exc)}).encode())
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    print(f"PEREZ dashboard listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
