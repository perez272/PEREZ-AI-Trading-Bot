"""Persistent expiry-aware learning for observed option surge events."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/memory/expiry_observations.sqlite3")

class ExpiryLearningEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path); self.db_path.parent.mkdir(parents=True, exist_ok=True); self._init()
    def _db(self):
        db=sqlite3.connect(self.db_path); db.execute("PRAGMA journal_mode=WAL"); return db
    def _init(self):
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS surge_events (id INTEGER PRIMARY KEY, event_key TEXT UNIQUE, symbol TEXT, option_type TEXT, expiry TEXT, window_minutes INTEGER, move_pct REAL, ltp REAL, observed_ts TEXT, features_json TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_expiry_symbol ON surge_events(symbol,expiry,window_minutes)")
    @staticmethod
    def _expiry_bucket(expiry: Any, observed_ts: str) -> str:
        try:
            e=datetime.fromisoformat(str(expiry).replace("Z","+00:00")).date()
            o=datetime.fromisoformat(str(observed_ts).replace("Z","+00:00")).date()
            d=(e-o).days
            return "0DTE" if d<=0 else "1DTE" if d==1 else "2-3DTE" if d<=3 else "4-7DTE" if d<=7 else "8+DTE"
        except (TypeError,ValueError): return "UNKNOWN"
    def record_events(self, events: list[dict[str,Any]]) -> int:
        written=0
        with self._db() as db:
            for e in events or []:
                if not e.get("symbol") or not e.get("instrument_key") or float(e.get("current_ltp",0) or 0)<=0: continue
                expiry=e.get("expiry") or ""
                key="|".join(str(e.get(k,"")) for k in ("symbol","option_type","instrument_key","window_minutes","observed_ts"))
                features=dict(e); features["expiry_bucket"]=self._expiry_bucket(expiry,e.get("observed_ts",""))
                cur=db.execute("INSERT OR IGNORE INTO surge_events(event_key,symbol,option_type,expiry,window_minutes,move_pct,ltp,observed_ts,features_json) VALUES(?,?,?,?,?,?,?,?,?)",(key,e.get("symbol"),e.get("option_type"),expiry,int(e.get("window_minutes",0)),float(e.get("move_pct",0)),float(e.get("current_ltp",0)),e.get("observed_ts"),json.dumps(features,separators=(",",":"))))
                written += cur.rowcount
        return written
    def stats(self)->dict[str,Any]:
        with self._db() as db:
            total=db.execute("SELECT COUNT(*) FROM surge_events").fetchone()[0]
            windows={int(w):int(n) for w,n in db.execute("SELECT window_minutes,COUNT(*) FROM surge_events GROUP BY window_minutes")}
            buckets={str(b):int(n) for b,n in db.execute("SELECT json_extract(features_json,'$.expiry_bucket'),COUNT(*) FROM surge_events GROUP BY 1")}
        return {"events":total,"by_window":windows,"by_expiry_bucket":buckets,"database":str(self.db_path)}

_default_engine=ExpiryLearningEngine()
def record_surge_events(events:list[dict[str,Any]])->int: return _default_engine.record_events(events)
def expiry_learning_stats()->dict[str,Any]: return _default_engine.stats()
def get_expiry_learning_engine()->ExpiryLearningEngine: return _default_engine
