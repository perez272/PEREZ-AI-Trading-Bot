"""Paper-only strategy analytics for the dashboard.

This module is observational only. It never changes strategy, risk limits,
entry controls, or order state. Missing evidence is reported as UNAVAILABLE.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data" / "memory" / "perez_ai_memory.db"
TEL = ROOT / "data" / "memory" / "dashboard_telemetry.sqlite3"


def _rows(db: Path, sql: str, args=(), limit=5000):
    try:
        with sqlite3.connect(db, timeout=3) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(sql, args).fetchmany(limit)]
    except Exception:
        return []


def _details(row):
    d = row.get("details") if isinstance(row, dict) else None
    if isinstance(d, dict):
        return d
    raw = row.get("details_json") if isinstance(row, dict) else None
    try:
        x = json.loads(raw or "{}")
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _num(*values):
    for v in values:
        try:
            if v is not None and str(v) != "":
                return float(v)
        except Exception:
            pass
    return None


def _pct(n, d):
    return round(n / d * 100.0, 1) if d else None


def _samples():
    rows = _rows(TEL, "SELECT * FROM lifecycle ORDER BY id ASC", limit=20000)
    grouped = defaultdict(list)
    for r in rows:
        grouped[r.get("event_key")].append(r)
    out = []
    for key, items in grouped.items():
        entry = next((r for r in items if r.get("stage") == "PAPER_ENTRY" and r.get("status") in ("OK", "PASS")), None)
        outcome = next((r for r in items if r.get("stage") == "OUTCOME" and r.get("status") in ("OK", "PASS")), None)
        if not entry or not outcome:
            continue
        ed = _details(entry); od = _details(outcome)
        pnl = _num(od.get("pnl"), outcome.get("pnl"))
        if pnl is None:
            continue
        try:
            dt = datetime.fromisoformat(str(entry.get("ts")))
        except Exception:
            continue
        x = {
            "event_key": key, "entry_ts": entry.get("ts"), "symbol": entry.get("symbol"),
            "option_type": entry.get("option_type"), "contract": entry.get("contract"),
            "score": _num(entry.get("score"), ed.get("score")), "pnl": pnl,
            "minute": dt.hour * 60 + dt.minute,
        }
        for name in ("move_1m_pct", "move_3m_pct", "move_5m_pct", "volume_ratio", "spread_pct", "acceleration", "ltp", "underlying_move_pct", "mfe", "mae", "mfe_pct", "mae_pct", "regime", "exit_reason"):
            x[name] = ed.get(name, od.get(name))
        x["exit_reason"] = od.get("exit_reason", x.get("exit_reason"))
        out.append(x)
    return out


def _timing(samples):
    buckets = {}
    for s in samples:
        start = (s["minute"] // 30) * 30
        label = f"{start//60:02d}:{start%60:02d}-{(start+30)//60:02d}:{(start+30)%60:02d}"
        b = buckets.setdefault(label, {"window": label, "samples": 0, "wins": 0, "net_pnl": 0.0})
        b["samples"] += 1; b["wins"] += int(s["pnl"] > 0); b["net_pnl"] += s["pnl"]
    for b in buckets.values():
        b["net_pnl"] = round(b["net_pnl"], 2); b["win_rate_pct"] = _pct(b["wins"], b["samples"])
    return sorted(buckets.values(), key=lambda x: x["window"])


def _entry_quality(samples):
    if not samples:
        return {"status": "UNAVAILABLE", "samples": 0, "win_rate_pct": None, "avg_pnl": None}
    wins = sum(s["pnl"] > 0 for s in samples)
    return {"status": "OBSERVED", "samples": len(samples), "win_rate_pct": _pct(wins, len(samples)), "avg_pnl": round(sum(s["pnl"] for s in samples) / len(samples), 2)}


def _loss_analysis(samples):
    losses = [s for s in samples if s["pnl"] < 0]
    reasons = defaultdict(lambda: {"count": 0, "net_pnl": 0.0})
    for s in losses:
        r = str(s.get("exit_reason") or "UNKNOWN")
        reasons[r]["count"] += 1; reasons[r]["net_pnl"] += s["pnl"]
    for v in reasons.values(): v["net_pnl"] = round(v["net_pnl"], 2)
    return {"losses": len(losses), "net_loss": round(sum(s["pnl"] for s in losses), 2), "by_exit_reason": dict(reasons)}


def _mfe_mae(samples):
    usable = [s for s in samples if _num(s.get("mfe"), s.get("mfe_pct")) is not None or _num(s.get("mae"), s.get("mae_pct")) is not None]
    if not usable:
        return {"status": "UNAVAILABLE", "samples": 0, "note": "MFE/MAE is not yet present in lifecycle telemetry."}
    mfes = [_num(s.get("mfe"), s.get("mfe_pct")) for s in usable]
    maes = [_num(s.get("mae"), s.get("mae_pct")) for s in usable]
    mfes = [x for x in mfes if x is not None]; maes = [x for x in maes if x is not None]
    return {"status": "OBSERVED", "samples": len(usable), "avg_mfe": round(sum(mfes)/len(mfes), 2) if mfes else None, "avg_mae": round(sum(maes)/len(maes), 2) if maes else None}


def _regime(samples):
    groups = defaultdict(list)
    for s in samples:
        r = str(s.get("regime") or "UNKNOWN").upper()
        groups[r].append(s)
    out = []
    for r, xs in groups.items():
        out.append({"regime": r, "samples": len(xs), "win_rate_pct": _pct(sum(x["pnl"] > 0 for x in xs), len(xs)), "net_pnl": round(sum(x["pnl"] for x in xs), 2)})
    return sorted(out, key=lambda x: x["net_pnl"], reverse=True)


def _cepe(samples):
    out = {}
    for side in ("CE", "PE"):
        xs = [s for s in samples if str(s.get("option_type") or "").upper() == side]
        out[side] = {"samples": len(xs), "win_rate_pct": _pct(sum(x["pnl"] > 0 for x in xs), len(xs)) if xs else None, "net_pnl": round(sum(x["pnl"] for x in xs), 2) if xs else 0.0}
    return out


def build_lab():
    samples = _samples()
    timing = _timing(samples)
    proven = len(samples) >= 30 and sum(1 for b in timing if b["samples"] >= 5) >= 3
    return {
        "status": "READY" if samples else "WAITING_FOR_COMPLETED_PAPER_TRADES",
        "safety": "OBSERVATION_ONLY",
        "sample_count": len(samples),
        "entry_quality": _entry_quality(samples),
        "timing": {"status": "PROVEN" if proven else "UNPROVEN", "samples": len(samples), "windows": timing, "minimum_samples": 30, "minimum_windows": 3},
        "loss_analysis": _loss_analysis(samples),
        "mfe_mae": _mfe_mae(samples),
        "regime": _regime(samples),
        "ce_pe": _cepe(samples),
        "counterfactual": {"status": "OBSERVATION_ONLY", "note": "No hypothetical trade is converted into a real or paper order; counterfactuals are analytical only."},
        "guardrails": ["PAPER_MODE remains authoritative", "ORDERS_ENABLED remains authoritative", "Risk manager remains authoritative", "Dashboard cannot bypass option/session/affordability gates"],
    }
