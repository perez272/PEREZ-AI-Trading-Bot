"""Read-only AI options scenario data for the Workstation.

This module exposes recorded paper-trade paths and explicitly rejected setups.
It never creates orders, changes strategy settings, or invents missing prices.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.expiry_oi_shadow import latest_observations as _latest_expiry_oi_observations
from src.sniper_expiry_simulation import build_sniper_observations, compare_runner_scenarios

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


ESTIMATED_PAPER_BROKERAGE_INR = 30.0


def _trade_accounting(path: Path = ROOT / "data" / "trades.csv") -> dict[str, dict[str, Any]]:
    """Read accounting by trade_id without silently selecting duplicate CSV rows."""
    if not path.exists():
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                trade_id = str(row.get("trade_id") or "").strip()
                if trade_id:
                    grouped.setdefault(trade_id, []).append(row)
    except (OSError, csv.Error):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for trade_id, rows in grouped.items():
        if len(rows) != 1:
            result[trade_id] = {
                "csv_row_count": len(rows), "accounting_status": "DUPLICATE_TRADE_ID",
                "brokerage_inr": None, "net_pnl": None,
            }
            continue
        row = rows[0]
        brokerage = _number(row.get("brokerage_inr"))
        gross = _number(row.get("pnl"))
        net = _number(row.get("net_pnl"))
        if net is None and gross is not None and brokerage is not None:
            net = round(gross - brokerage, 2)
        result[trade_id] = {
            "csv_row_count": 1,
            "accounting_status": "RECORDED_ACCOUNTING_AVAILABLE" if brokerage is not None else "CSV_ROW_MATCHED_FEE_MISSING",
            "brokerage_inr": brokerage,
            "net_pnl": net if brokerage is not None else None,
        }
    return result


def _paper_trades(
    events: list[dict[str, Any]],
    trades_csv: Path = ROOT / "data" / "trades.csv",
) -> list[dict[str, Any]]:
    accounting = _trade_accounting(trades_csv)
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
            "recorded_gross_pnl": _number(close.get("pnl"), close.get("realized_pnl")) if close else None,
            "recorded_brokerage_inr": accounting.get(trade_id, {}).get("brokerage_inr") if close else None,
            "recorded_net_pnl": accounting.get(trade_id, {}).get("net_pnl") if close else None,
            "accounting_source": "data/trades.csv" if trade_id in accounting else "NO_CSV_ROW_MATCH",
            "accounting_status": accounting.get(trade_id, {}).get("accounting_status", "NO_CSV_ROW_MATCH") if close else "NOT_CLOSED",
            "accounting_csv_row_count": accounting.get(trade_id, {}).get("csv_row_count", 0) if close else 0,
            "estimated_brokerage_inr": (
                ESTIMATED_PAPER_BROKERAGE_INR
                if close and _number(close.get("pnl"), close.get("realized_pnl")) is not None
                and accounting.get(trade_id, {}).get("brokerage_inr") is None else None
            ),
            "estimated_net_pnl": (
                round(_number(close.get("pnl"), close.get("realized_pnl")) - ESTIMATED_PAPER_BROKERAGE_INR, 2)
                if close and _number(close.get("pnl"), close.get("realized_pnl")) is not None
                and accounting.get(trade_id, {}).get("brokerage_inr") is None else None
            ),
            "estimated_accounting_basis": (
                "FLAT_PAPER_FEE_ASSUMPTION_30_INR_NOT_RECORDED"
                if close and _number(close.get("pnl"), close.get("realized_pnl")) is not None
                and accounting.get(trade_id, {}).get("brokerage_inr") is None else None
            ),
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


def _sniper_runner_comparisons(paper: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the all-quantity Sniper trail only on recorded paper-trade price paths."""
    results = []
    for trade in paper:
        replay_brokerage = (
            trade.get("recorded_brokerage_inr")
            if trade.get("recorded_brokerage_inr") is not None
            else ESTIMATED_PAPER_BROKERAGE_INR
        )
        replay_brokerage_basis = (
            "RECORDED_FEE" if trade.get("recorded_brokerage_inr") is not None
            else "SIMULATION_ASSUMPTION_30_INR_NOT_RECORDED"
        )
        result = compare_runner_scenarios(
            trade.get("path") or [], trade.get("entry"), trade.get("stop_loss"),
            int(trade.get("quantity") or 0), brokerage=replay_brokerage,
        )
        results.append({
            "trade_id": trade.get("id"), "symbol": trade.get("symbol"),
            "contract": trade.get("contract"),
            "recorded_pnl": trade.get("recorded_gross_pnl"),
            "recorded_gross_pnl": trade.get("recorded_gross_pnl"),
            "recorded_brokerage_inr": trade.get("recorded_brokerage_inr"),
            "recorded_net_pnl": trade.get("recorded_net_pnl"),
            "accounting_source": trade.get("accounting_source"),
            "accounting_status": trade.get("accounting_status", "UNKNOWN"),
            "replay_brokerage_inr": replay_brokerage,
            "replay_brokerage_basis": replay_brokerage_basis,
            **result,
        })
    return results


def build_simulations() -> dict[str, Any]:
    events = _read_lifecycle()
    rejections = _rejections()
    paper = _paper_trades(events)
    rejected = _rejected_scenarios(rejections)
    shadow = _shadow_paths(rejections)
    expiry_oi = _latest_expiry_oi_observations()
    sniper_observations = build_sniper_observations(expiry_oi)
    sniper_runner_comparisons = _sniper_runner_comparisons(paper)
    shadow_by_id = {item["id"]: item for item in shadow}
    rejected = [shadow_by_id.get(item["id"], item) for item in rejected]
    known = {item["id"] for item in rejected}
    rejected.extend(item for item in shadow if item["id"] not in known)
    return {
        "status": "READY" if paper or rejected or expiry_oi else "WAITING_FOR_RECORDED_DATA",
        "safety": "OBSERVATION_ONLY",
        "generated_from": ["paper_trade_lifecycle.jsonl", "perez_ai_memory.db:rejections", "adaptive_trade_memory.sqlite3:surge_outcomes", "expiry_oi_shadow.sqlite3"],
        "paper_trades": paper,
        "rejected_scenarios": rejected,
        "expiry_oi_observations": expiry_oi,
        "sniper_expiry_observations": sniper_observations,
        "sniper_runner_comparisons": sniper_runner_comparisons,
        "counts": {"paper_trades": len(paper), "rejected_scenarios": len(rejected), "expiry_oi_observations": len(expiry_oi), "sniper_expiry_observations": len(sniper_observations), "sniper_confirmed": sum(1 for x in sniper_observations if x["eligible"]), "sniper_runner_comparisons": len(sniper_runner_comparisons)},
        "disclaimer": "Expiry/OI and Sniper signals are observation-only. Missing ORB, multi-timeframe, volume, Greeks, or historical premium-path evidence fails closed; these results never authorize entries or orders. Hypothetical rejected setups are not executed trades. Missing entry, stop, target, or historical quote data is left unavailable; no synthetic prices or P&L are generated.",
    }
