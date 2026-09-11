"""Forward-outcome learning for Tier-1 surge events.

Detection features are frozen at detection time. Outcomes are populated only
from quotes observed strictly after detection, preventing future-data leakage.
This layer is advisory and never changes risk/order controls.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/adaptive_trade_memory.sqlite3")
HORIZONS = (1, 3, 5, 10, 15)


def _db(path: Path | str = DB_PATH):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _pct(price: float, entry: float) -> float:
    return ((price - entry) / entry * 100.0) if entry > 0 else 0.0


def _init(path: Path | str = DB_PATH) -> None:
    with _db(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS surge_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            option_type TEXT NOT NULL,
            instrument_key TEXT NOT NULL,
            expiry TEXT, strike REAL, detection_ts TEXT NOT NULL,
            entry_ltp REAL NOT NULL, score REAL,
            features_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'UNRESOLVED',
            source TEXT NOT NULL DEFAULT 'live'
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS surge_outcomes (
            candidate_id INTEGER PRIMARY KEY,
            h1_ltp REAL, h3_ltp REAL, h5_ltp REAL, h10_ltp REAL, h15_ltp REAL,
            mfe_pct REAL NOT NULL DEFAULT 0,
            mae_pct REAL NOT NULL DEFAULT 0,
            continuation_pct REAL,
            reversal_pct REAL,
            label TEXT NOT NULL DEFAULT 'UNRESOLVED',
            resolved_ts TEXT,
            FOREIGN KEY(candidate_id) REFERENCES surge_candidates(id)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_surge_candidates_instrument_ts ON surge_candidates(instrument_key,detection_ts)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_surge_candidates_status ON surge_candidates(status)")


def pattern_key(features: dict[str, Any]) -> str:
    frozen = {k: features.get(k) for k in sorted(features) if k not in {"ltp", "detection_ts", "observed_ts"}}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, default=str).encode()).hexdigest()[:24]


def remember_surge(event: dict[str, Any], event_key: str | None = None, path: Path | str = DB_PATH) -> int:
    _init(path)
    key = str(event_key or event.get("event_key") or "")
    instrument = str(event.get("instrument_key") or "")
    ts = str(event.get("detection_ts") or event.get("observed_ts") or "")
    ltp = float(event.get("ltp") or 0)
    if not key or not instrument or not ts or ltp <= 0:
        return 0
    features = event.get("features") if isinstance(event.get("features"), dict) else {}
    features = dict(features)
    features["pattern_key"] = pattern_key(features)
    with _db(path) as db:
        cur = db.execute("""INSERT OR IGNORE INTO surge_candidates(
            event_key,symbol,option_type,instrument_key,expiry,strike,detection_ts,
            entry_ltp,score,features_json,status,source
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
            key, str(event.get("symbol") or ""), str(event.get("option_type") or ""), instrument,
            event.get("expiry"), event.get("strike"), ts, ltp, float(event.get("score") or 0),
            json.dumps(features, separators=(",", ":"), default=str), "UNRESOLVED", "live"
        ))
        row = db.execute("SELECT id FROM surge_candidates WHERE event_key=?", (key,)).fetchone()
        return int(row[0]) if row else 0


def record_quote(instrument_key: str, observed_ts: str, ltp: float, path: Path | str = DB_PATH) -> int:
    """Attach one fresh quote to all unresolved candidates for this instrument."""
    _init(path)
    try: price = float(ltp)
    except (TypeError, ValueError): return 0
    if not instrument_key or price <= 0: return 0
    now = _epoch(observed_ts)
    if now is None: return 0
    changed = 0
    with _db(path) as db:
        rows = db.execute("SELECT id,detection_ts,entry_ltp FROM surge_candidates WHERE instrument_key=? AND status='UNRESOLVED'", (instrument_key,)).fetchall()
        for cid, dts, entry in rows:
            det = _epoch(dts)
            if det is None or now <= det or entry <= 0: continue
            age = (now - det) / 60.0
            out = db.execute("SELECT h1_ltp,h3_ltp,h5_ltp,h10_ltp,h15_ltp,mfe_pct,mae_pct FROM surge_outcomes WHERE candidate_id=?", (cid,)).fetchone()
            if out is None:
                out = (None, None, None, None, None, 0.0, 0.0)
                db.execute("INSERT OR IGNORE INTO surge_outcomes(candidate_id) VALUES(?)", (cid,))
            vals = list(out)
            future_pct = _pct(price, float(entry))
            vals[5] = max(float(vals[5] or 0), future_pct)
            vals[6] = min(float(vals[6] or 0), future_pct)
            for i, horizon in enumerate(HORIZONS):
                if vals[i] is None and age >= horizon:
                    vals[i] = price
            h5 = vals[2]
            h15 = vals[4]
            label = None
            if h15 is not None:
                final_pct = _pct(float(h15), float(entry))
                mfe = float(vals[5] or 0)
                mae = float(vals[6] or 0)
                if mfe >= 15.0 and final_pct >= 5.0: label = "STRONG_WIN"
                elif final_pct >= 5.0 or mfe >= 10.0: label = "WIN"
                elif final_pct <= -5.0 or mae <= -10.0: label = "FALSE_SURGE"
                else: label = "FLAT"
            db.execute("""UPDATE surge_outcomes SET h1_ltp=?,h3_ltp=?,h5_ltp=?,h10_ltp=?,h15_ltp=?,mfe_pct=?,mae_pct=?,
                continuation_pct=?,reversal_pct=?,label=?,resolved_ts=? WHERE candidate_id=?""", (
                vals[0],vals[1],vals[2],vals[3],vals[4],round(vals[5],2),round(vals[6],2),
                _pct(float(h5),float(entry)) if h5 is not None else None,
                round(min(0.0,float(vals[6] or 0)),2), label or "UNRESOLVED",
                observed_ts if label else None, cid
            ))
            if label: changed += 1
    return changed


def backfill_existing_surge_candidates(source_db: Path | str = "data/memory/tier1_option_moves.sqlite3", path: Path | str = DB_PATH) -> int:
    """Import retained historical detections without inventing any outcome."""
    _init(path)
    src = Path(source_db)
    if not src.exists(): return 0
    with sqlite3.connect(src) as s, _db(path) as db:
        rows = s.execute("""SELECT event_key,symbol,option_type,instrument_key,expiry,strike,ltp,score,
            move_1m_pct,move_3m_pct,move_5m_pct,velocity,acceleration,volume_ratio,spread_pct,
            reasons_json,features_json,observed_ts,detection_ts FROM early_events""").fetchall()
        added = 0
        for r in rows:
            key,symbol,opt,inst,expiry,strike,ltp,score,*rest = r
            observed_ts,detection_ts = r[-2],r[-1]
            if not key or not inst or not ltp or not detection_ts: continue
            features = {}
            try: features = json.loads(r[-3]) if r[-3] else {}
            except (TypeError,ValueError,json.JSONDecodeError): pass
            features["move_1m_pct"] = r[9]; features["move_3m_pct"] = r[10]; features["move_5m_pct"] = r[11]
            features["velocity"] = r[12]; features["acceleration"] = r[13]; features["volume_ratio"] = r[14]; features["spread_pct"] = r[15]
            cur = db.execute("""INSERT OR IGNORE INTO surge_candidates(event_key,symbol,option_type,instrument_key,expiry,strike,detection_ts,entry_ltp,score,features_json,status,source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (key,symbol,opt,inst,expiry,strike,detection_ts,float(ltp),float(score or 0),json.dumps(features,separators=(",",":"),default=str),"UNRESOLVED","historical"))
            added += cur.rowcount
        return added


def stats(path: Path | str = DB_PATH) -> dict[str, Any]:
    _init(path)
    with _db(path) as db:
        total = db.execute("SELECT COUNT(*) FROM surge_candidates").fetchone()[0]
        resolved = db.execute("SELECT COUNT(*) FROM surge_candidates WHERE status!='UNRESOLVED'").fetchone()[0]
        labels = dict(db.execute("SELECT label,COUNT(*) FROM surge_outcomes GROUP BY label").fetchall())
        return {"candidates": int(total), "resolved": int(resolved), "unresolved": int(total-resolved), "labels": labels}


def learning_signal(event: dict[str, Any], min_samples: int = 10, path: Path | str = DB_PATH) -> dict[str, Any]:
    """Return bounded advisory score adjustment from mature resolved patterns."""
    _init(path)
    features = event.get("features") if isinstance(event.get("features"), dict) else dict(event)
    pk = pattern_key(features)
    with _db(path) as db:
        rows = db.execute("SELECT o.label FROM surge_outcomes o JOIN surge_candidates c ON c.id=o.candidate_id WHERE o.label!='UNRESOLVED' AND json_extract(c.features_json,'$.pattern_key')=?", (pk,)).fetchall()
    n = len(rows)
    if n < min_samples: return {"status":"COLD_START","adjustment":0.0,"confidence":0.0,"samples":n}
    strong = sum(1 for (x,) in rows if x == "STRONG_WIN")
    wins = sum(1 for (x,) in rows if x == "WIN")
    false = sum(1 for (x,) in rows if x == "FALSE_SURGE")
    score = (strong * 1.0 + wins * 0.5 - false * 1.0) / max(1,n)
    adj = round(max(-8.0,min(8.0,score*8.0)),2)
    return {"status":"LEARNED","adjustment":adj,"confidence":round(min(1.0,n/50.0),2),"samples":n}


_init()
