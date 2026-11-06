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
                   event.get("current_ltp"), event.get("entry"), event.get("entry_price"))


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



def _shadow_paths(rows: list[dict[str, Any]], db: Path = ROOT / "data" / "memory" / "adaptive_trade_memory.sqlite3") -> list[dict[str, Any]]:
    """Attach only persisted post-detection quotes to genuine rejected surge events."""
    if not db.exists():
        return []
    keys = {}
    for row in rows:
        details = _details(row)
        raw = details.get("features_json") or row.get("features_json")
        if isinstance(raw, str):
            try:
                details = {**details, **json.loads(raw)}
            except (TypeError, ValueError):
                pass
        event = details.get("event") if isinstance(details.get("event"), dict) else {}
        key = event.get("event_key") or details.get("event_key")
        if key:
            keys[str(key)] = row
    if not keys:
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            candidates = conn.execute(
                "SELECT c.event_key,c.symbol,c.option_type,c.instrument_key,c.expiry,c.strike,"
                "c.detection_ts,c.entry_ltp,c.score,o.h1_ltp,o.h3_ltp,o.h5_ltp,o.h10_ltp,"
                "o.h15_ltp,o.mfe_pct,o.mae_pct,o.label,o.resolved_ts "
                "FROM surge_candidates c LEFT JOIN surge_outcomes o ON o.candidate_id=c.id "
                "WHERE c.event_key IN (" + ",".join("?" for _ in keys) + ")",
                tuple(keys),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    result = []
    for item in candidates:
        row = keys.get(item["event_key"])
        if not row:
            continue
        prices = [item[f"h{h}_ltp"] for h in (1, 3, 5, 10, 15)]
        path = [{"time": f"+{h}m", "event": f"SHADOW_H{h}", "price": float(price)}
                for h, price in zip((1, 3, 5, 10, 15), prices) if price is not None]
        entry = _number(item["entry_ltp"])
        details = _details(row)
        raw = details.get("features_json") or row.get("features_json")
        if isinstance(raw, str):
            try:
                details = {**details, **json.loads(raw)}
            except (TypeError, ValueError):
                pass
        event = details.get("event") if isinstance(details.get("event"), dict) else {}
        merged = {**event, **details}
        result.append({
            "id": str(row.get("id") or item["event_key"]), "kind": "REJECTED",
            "symbol": item["symbol"], "contract": merged.get("contract") or item["instrument_key"],
            "reason": row.get("reason"), "time": item["detection_ts"],
            "score": _number(item["score"], row.get("score")), "entry": entry,
            "stop_loss": _number(merged.get("stop_loss"), merged.get("sl")),
            "target1": _number(merged.get("target1"), merged.get("target_1")),
            "target2": _number(merged.get("target2"), merged.get("target_2")),
            "path": ([{"time": item["detection_ts"], "event": "DETECTION_ENTRY_REFERENCE", "price": entry}]
                     if entry is not None else []) + path,
            "pnl": None, "return_pct": ((float(item["h15_ltp"])-entry)/entry*100.0
                                         if entry and item["h15_ltp"] is not None else None),
            "mfe_pct": _number(item["mfe_pct"]), "mae_pct": _number(item["mae_pct"]),
            "outcome_label": item["label"], "resolved_time": item["resolved_ts"],
            "source": "adaptive_trade_memory.sqlite3:surge_candidates+surge_outcomes",
            "data_quality": "RECORDED_SHADOW_PATH" if path else "ENTRY_REFERENCE_ONLY",
            "quantity": None, "note": "Observed option-price path after rejection; not an executed trade. No hypothetical rupee P&L or missing levels are inferred.",
        })
    return result

def build_simulations() -> dict[str, Any]:
    events = _read_lifecycle()
    rejections = _rejections()
    paper = _paper_trades(events)
    rejected = _rejected_scenarios(rejections)
    rejected.extend(_shadow_paths(rejections))
    return {
        "status": "READY" if paper or rejected else "WAITING_FOR_RECORDED_DATA",
        "safety": "OBSERVATION_ONLY",
        "generated_from": ["paper_trade_lifecycle.jsonl", "perez_ai_memory.db:rejections"],
        "paper_trades": paper,
        "rejected_scenarios": rejected,
        "counts": {"paper_trades": len(paper), "rejected_scenarios": len(rejected)},
        "disclaimer": "Hypothetical rejected setups are not executed trades. Missing entry, stop, target, or historical quote data is left unavailable; no synthetic prices or P&L are generated.",
    }
