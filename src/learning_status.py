"""Read-only runtime/learning telemetry for Telegram and diagnostics.

This module never changes trading decisions. It only reports persisted evidence.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.risk_manager import daily_summary
from src.tier1_option_observer import get_tier1_option_observer

STATUS_PATH = Path("data/runtime/learning_status.json")
TRADES_PATH = Path("data/trades.csv")


def _load() -> dict[str, Any]:
    try:
        if STATUS_PATH.exists():
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    return {"rejections": 0, "lessons_events": 0, "last_observation": None, "last_events": []}


def _persist(data: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STATUS_PATH)


def record_cycle(*, observations: int = 0, rejections: int = 0, lessons_events: int = 0, events: list[dict[str, Any]] | None = None) -> None:
    data = _load()
    data["rejections"] = int(data.get("rejections", 0)) + max(0, int(rejections))
    data["lessons_events"] = int(data.get("lessons_events", 0)) + max(0, int(lessons_events))
    if events:
        data["last_events"] = events[-10:]
    _persist(data)


def _historical_trade_stats() -> tuple[int, float]:
    if not TRADES_PATH.exists():
        return 0, 0.0
    wins = 0
    closed = 0
    try:
        with TRADES_PATH.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if not row.get("closed_at"):
                    continue
                try:
                    pnl = float(row.get("pnl", 0) or 0)
                except (TypeError, ValueError):
                    continue
                closed += 1
                if pnl > 0:
                    wins += 1
    except (OSError, csv.Error):
        return 0, 0.0
    return wins, round((wins / closed * 100.0) if closed else 0.0, 2)


def get_learning_status() -> dict[str, Any]:
    observer = get_tier1_option_observer()
    observer_stats = observer.stats()
    data = _load()
    risk = daily_summary()
    wins, win_rate = _historical_trade_stats()
    observations = int(observer_stats.get("observations", 0) or 0)
    # A timestamp in learning_status.json is only bookkeeping. The authoritative
    # observation count comes from the observer's persisted SQLite evidence.
    last_observation = data.get("last_observation") if observations > 0 else None
    return {
        "completed_paper_trades": risk["closed_trades"],
        "wins": wins,
        "learned_win_rate": win_rate,
        "learned_pnl": risk["pnl"],
        "observations": observations,
        "rejections": int(data.get("rejections", 0)),
        "lessons_events": int(data.get("lessons_events", 0)),
        "option_surge_events": observer_stats.get("surge_events", 0),
        "outcome_learning": "READY" if risk["closed_trades"] else "WAITING_FOR_FIRST_CLOSED_TRADE",
        "pattern_learning": "READY" if observations else "WAITING_FOR_OBSERVATIONS",
        "last_observation": last_observation,
        "last_events": data.get("last_events", []),
    }
