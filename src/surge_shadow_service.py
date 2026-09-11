"""Independent shadow-rank recorder for every Tier-1 early surge event.
Observational only: records raw-vs-learned priority before the 15m outcome resolves.
Never changes entries, risk, orders, or trade limits.
"""
from __future__ import annotations
import json,sqlite3,time,signal,os
from pathlib import Path
from src.surge_outcome_learning import learning_signal,record_shadow_ranking
DB=Path(os.getenv("TIER1_OPTION_MEMORY","data/memory/tier1_option_moves.sqlite3"))
POLL=max(1,int(os.getenv("SURGE_SHADOW_INTERVAL_SECONDS","2")))
RUNNING=True

def _stop(*_):
 global RUNNING;RUNNING=False

def _scan(limit=200):
 if not DB.exists(): return 0
 try:
  with sqlite3.connect(DB) as db:
   rows=db.execute("SELECT e.event_key,e.symbol,e.option_type,e.instrument_key,e.expiry,e.strike,e.ltp,e.score,e.move_1m_pct,e.move_3m_pct,e.move_5m_pct,e.velocity,e.acceleration,e.volume_ratio,e.spread_pct,e.features_json,e.observed_ts,e.detection_ts FROM early_events e LEFT JOIN surge_shadow_rankings s ON s.event_key=e.event_key WHERE julianday(e.detection_ts) >= julianday('now','-2 hours') AND s.event_key IS NULL ORDER BY e.id DESC LIMIT ?",(limit,)).fetchall()
 except Exception:
  return 0
 done=0
 for r in rows:
  try:
   f=json.loads(r[15]) if r[15] else {}
  except (TypeError,ValueError,json.JSONDecodeError): f={}
  e={"event_key":r[0],"symbol":r[1],"option_type":r[2],"instrument_key":r[3],"expiry":r[4],"strike":r[5],"ltp":r[6],"score":r[7],"move_1m_pct":r[8],"move_3m_pct":r[9],"move_5m_pct":r[10],"velocity":r[11],"acceleration":r[12],"volume_ratio":r[13],"spread_pct":r[14],"features":f,"observed_ts":r[16],"detection_ts":r[17]}
  try:
   s=learning_signal(e)
   expected=max(-4.0,min(4.0,float(s.get("expected_return_pct",0) or 0)))
   adj=max(-8.0,min(8.0,float(s.get("adjustment",0) or 0))) if s.get("status")=="LEARNED" else 0.0
   learned=float(e["score"] or 0)+adj+expected
   done+=record_shadow_ranking(e,learned)
  except Exception:
   continue
 return done

def main():
 signal.signal(signal.SIGTERM,_stop);signal.signal(signal.SIGINT,_stop)
 print("PEREZ AI Surge Shadow Rank Service — OBSERVATION ONLY")
 while RUNNING:
  n=_scan()
  if n: print(f"[SHADOW RANK] recorded={n}")
  time.sleep(POLL)

if __name__=="__main__": main()
