"""Read-only AI options scenario data for the Workstation.

This module exposes recorded paper-trade paths and explicitly rejected setups.
It never creates orders, changes strategy settings, or invents missing prices.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data" / "memory" / "perez_ai_memory.db"
LIFECYCLE = ROOT / "data" / "paper_trade_lifecycle.jsonl"


def _number(*values: Any) -> float | None:
    for value in values:
        try:
            if value is not None and str(value).strip() != "":
                result = float(value)
                if result == result and abs(result) != float("inf"):
                    return result
        except (TypeError, ValueError):
            continue
    return None


def _read_lifecycle(path: Path = LIFECYCLE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        events.append(item)
                except (TypeError, ValueError):
                    continue
    except OSError:
        return []
    return events[-30000:]


def _details(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("details")
    if isinstance(value, dict):
        return value
    for key in ("details_json", "metadata_json", "metadata"):
        raw = row.get(key)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, ValueError):
                pass
    return {}


def _rejections(db: Path = CORE) -> list[dict[str, Any]]:
    if not db.exists():
        return []
    try:
        with sqlite3.connect(db, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(rejections)")}
            if not columns:
                return []
            rows = conn.execute("SELECT * FROM rejections ORDER BY rowid DESC LIMIT 100").fetchall()
            return [dict(row) for row in rows]
    except (sqlite3.Error, OSError):
        return []


def _event_price(event: dict[str, Any]) -> float | None:
    return _number(event.get("ltp"), event.get("price"), event.get("option_ltp"),
                   event.get("mark_price"), event.get("exit_price"),
                   event.get("current_ltp"))


def _paper_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        trade_id = str(event.get("trade_id") or event.get("lineage_id") or "")
        if trade_id:
            grouped.setdefault(trade_id, []).append(event)

    result = []
    for trade_id, items in grouped.items():
        opened = next((e for e in items if str(e.get("event", "")).upper() in {"OPEN", "ENTRY"}), None)
        if not opened:
            continue
        items.sort(key=lambda e: str(e.get("ts_utc") or e.get("ts_ist") or e.get("ts") or ""))
        entry = _number(opened.get("entry"), opened.get("entry_price"), opened.get("ltp"))
        levels = {
            "entry": entry,
            "stop_loss": _number(opened.get("stop_loss"), opened.get("sl")),
            "target1": _number(opened.get("target1"), opened.get("target_1")),
            "target2": _number(opened.get("target2"), opened.get("target_2")),
        }
        path = []
        for event in items:
            price = _event_price(event)
            if price is not None:
                path.append({
                    "time": event.get("ts_ist") or event.get("ts_utc") or event.get("ts"),
                    "event": event.get("event"),
                    "price": price,
                })
        close = next((e for e in reversed(items) if str(e.get("event", "")).upper() == "CLOSE"), None)
        result.append({
            "id": trade_id, "kind": "PAPER", "symbol": opened.get("symbol"),
            "contract": opened.get("contract"), "strategy": opened.get("strategy"),
            "status": "CLOSED" if close else "OPEN",
            "entry_time": opened.get("ts_ist") or opened.get("ts_utc") or opened.get("ts"),
            "entry": entry, "stop_loss": levels["stop_loss"],
            "target1": levels["target1"], "target2": levels["target2"],
            "quantity": _number(opened.get("quantity"), opened.get("qty")),
            "pnl": _number(close.get("pnl"), close.get("realized_pnl")) if close else None,
            "exit_reason": close.get("exit_reason") if close else None,
            "path": path, "source": "data/paper_trade_lifecycle.jsonl",
            "data_quality": "RECORDED_PATH" if len(path) > 1 else "ENTRY_ONLY",
        })
    result.sort(key=lambda x: str(x.get("entry_time") or ""), reverse=True)
    return result[:100]


def _rejected_scenarios(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, row in enumerate(rows):
        details = _details(row)
        merged = {**details, **row}
        entry = _number(merged.get("entry"), merged.get("entry_price"),
                        merged.get("option_ltp"), merged.get("ltp"))
        stop = _number(merged.get("stop_loss"), merged.get("sl"))
        target1 = _number(merged.get("target1"), merged.get("target_1"))
        target2 = _number(merged.get("target2"), merged.get("target_2"))
        missing = [name for name, value in (
            ("entry", entry), ("stop_loss", stop), ("target1", target1),
            ("target2", target2),
        ) if value is None]
        result.append({
            "id": str(merged.get("id") or merged.get("event_key") or f"rejection-{index}"),
            "kind": "REJECTED", "symbol": merged.get("symbol"),
            "contract": merged.get("contract") or merged.get("instrument_key"),
            "reason": merged.get("reason") or merged.get("reject_reason"),
            "time": merged.get("ts") or merged.get("created_at") or merged.get("timestamp"),
            "score": _number(merged.get("score"), merged.get("options_score")),
            "entry": entry, "stop_loss": stop, "target1": target1, "target2": target2,
            "path": [], "source": "perez_ai_memory.db:rejections",
            "data_quality": "LEVELS_RECORDED" if not missing else "INSUFFICIENT_RECORDED_DATA",
            "missing_fields": missing,
            "note": "No post-rejection option-price path is inferred. Historical quotes are shown only when recorded by a source.",
        })
    return result


def build_simulations() -> dict[str, Any]:
    events = _read_lifecycle()
    rejections = _rejections()
    paper = _paper_trades(events)
    rejected = _rejected_scenarios(rejections)
    return {
        "status": "READY" if paper or rejected else "WAITING_FOR_RECORDED_DATA",
        "safety": "OBSERVATION_ONLY",
        "generated_from": ["paper_trade_lifecycle.jsonl", "perez_ai_memory.db:rejections"],
        "paper_trades": paper,
        "rejected_scenarios": rejected,
        "counts": {"paper_trades": len(paper), "rejected_scenarios": len(rejected)},
        "disclaimer": "Hypothetical rejected setups are not executed trades. Missing entry, stop, target, or historical quote data is left unavailable; no synthetic prices or P&L are generated.",
    }
