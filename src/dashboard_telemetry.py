"""Persistent, paper-only lifecycle telemetry for the PEREZ dashboard."""
from __future__ import annotations
import json,sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/memory/dashboard_telemetry.sqlite3'; IST=ZoneInfo('Asia/Kolkata')
def _now():return datetime.now(IST).isoformat(timespec='milliseconds')
def _db():
 DB.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB,timeout=3);c.execute('PRAGMA journal_mode=WAL');c.execute("CREATE TABLE IF NOT EXISTS lifecycle(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL,ts TEXT NOT NULL,symbol TEXT,option_type TEXT,contract TEXT,score REAL,details_json TEXT NOT NULL DEFAULT '{}')");c.execute('CREATE INDEX IF NOT EXISTS idx_lifecycle_event ON lifecycle(event_key,id)');c.execute('CREATE INDEX IF NOT EXISTS idx_lifecycle_ts ON lifecycle(ts)');return c
def record_stage(event_key:str,stage:str,status:str='OK',**details:Any)->None:
 if not event_key:return
 try:
  override=details.pop('ts_override',None) or _now()
  with _db() as db:db.execute('INSERT INTO lifecycle(event_key,stage,status,ts,symbol,option_type,contract,score,details_json) VALUES (?,?,?,?,?,?,?,?,?)',(str(event_key),str(stage),str(status),override,details.pop('symbol',None),details.pop('option_type',None),details.pop('contract',None),details.pop('score',None),json.dumps(details,default=str,separators=(',',':'))))
 except Exception:pass
def recent(limit=160):
 try:
  with _db() as db:
   db.row_factory=sqlite3.Row;rows=db.execute('SELECT * FROM lifecycle ORDER BY id DESC LIMIT ?',(max(1,int(limit)),)).fetchall()
  out=[]
  for r in rows:
   d=dict(r)
   try:d['details']=json.loads(d.pop('details_json') or '{}')
   except Exception:d['details']={};d.pop('details_json',None)
   out.append(d)
  return out
 except Exception:return []
def event_proof(event_key):
 rows=[r for r in recent(1000) if r.get('event_key')==event_key];rows.sort(key=lambda r:r.get('id',0));stages={r['stage']:r for r in rows}
 def delta(a,b):
  if not a or not b:return None
  try:return max(0.0,(datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds())
  except Exception:return None
 return {'event_key':event_key,'stages':{k:stages.get(k) for k in ('DETECTED','BRIDGE_PICKUP','GATE_EVALUATION','PAPER_ENTRY','MONITOR_START','MONITOR_END','OUTCOME')},'timeline':rows,'detection_to_bridge_s':delta(stages.get('DETECTED',{}).get('ts'),stages.get('BRIDGE_PICKUP',{}).get('ts')),'bridge_to_entry_s':delta(stages.get('BRIDGE_PICKUP',{}).get('ts'),stages.get('PAPER_ENTRY',{}).get('ts')),'entry_to_monitor_s':delta(stages.get('PAPER_ENTRY',{}).get('ts'),stages.get('MONITOR_START',{}).get('ts')),'monitor_to_outcome_s':delta(stages.get('MONITOR_START',{}).get('ts'),stages.get('OUTCOME',{}).get('ts')),'total_to_outcome_s':delta(rows[0].get('ts') if rows else None,rows[-1].get('ts') if rows else None)}
def summary():
 rows=recent(2000);sc={};st={}
 for r in rows:sc[r['stage']]=sc.get(r['stage'],0)+1;st[r['status']]=st.get(r['status'],0)+1
 return {'records':len(rows),'stage_counts':sc,'status_counts':st}
