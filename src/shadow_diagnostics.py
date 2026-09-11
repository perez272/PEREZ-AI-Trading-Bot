"""Leakage-safe diagnostics for raw vs learned Tier-1 shadow ranking.
Observation/reporting only: never changes entries, risk, orders, or limits.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
DB_PATH=Path("data/memory/adaptive_trade_memory.sqlite3")
MIN_GROUP_SAMPLES=5

def _db(path=DB_PATH):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);return sqlite3.connect(p)

def _valid_rows(path=DB_PATH):
 with _db(path) as db:
  return db.execute("""SELECT c.symbol,c.option_type,c.score,c.features_json,r.raw_score,r.learned_score,r.created_ts,o.label,c.entry_ltp,o.h1_ltp,o.h3_ltp,o.h5_ltp,o.h10_ltp,o.h15_ltp,c.detection_ts,o.resolved_ts FROM surge_shadow_rankings r JOIN surge_candidates c ON c.event_key=r.event_key JOIN surge_outcomes o ON o.candidate_id=c.id WHERE o.label!='UNRESOLVED' AND julianday(r.created_ts)>=julianday(c.detection_ts) AND (julianday(r.created_ts)-julianday(c.detection_ts))*86400<=900 AND (o.resolved_ts IS NULL OR julianday(r.created_ts)<=julianday(o.resolved_ts))""").fetchall()

def _bucket(score):
 try:s=float(score)
 except (TypeError,ValueError):return "UNKNOWN"
 if s<60:return "<60"
 if s<70:return "60-70"
 if s<80:return "70-80"
 return "80+"

def _pct(price,entry):
 try:
  if price is None or entry is None or float(entry)<=0:return None
  return (float(price)-float(entry))/float(entry)*100
 except (TypeError,ValueError):return None

def _metrics(rows):
 n=len(rows)
 if not n:return {"samples":0}
 def ret(r,ix):
  return _pct(r[ix],r[8])
 def avg(ix):
  vals=[ret(r,ix) for r in rows if ret(r,ix) is not None]
  return round(sum(vals)/len(vals),3) if vals else None
 def top(metric_ix):
  ordered=sorted(rows,key=lambda r:float(r[metric_ix] or 0),reverse=True)
  k=max(1,(n+3)//4)
  selected=ordered[:k]
  vals=[ret(r,13) for r in selected if ret(r,13) is not None]
  expected=round(sum(vals)/len(vals),3) if vals else None
  strong=round(sum(r[7]=="STRONG_WIN" for r in selected)/len(selected),3)
  win=round(sum(r[7] in ("WIN","STRONG_WIN") for r in selected)/len(selected),3)
  false=round(sum(r[7]=="FALSE_SURGE" for r in selected)/len(selected),3)
  return k,expected,strong,win,false
 k,raw,raw_strong,raw_win,raw_false=top(4)
 _,learned,learned_strong,learned_win,learned_false=top(5)
 return {
  "samples":n,
  "top_quartile":k,
  "raw_top_expected_pct":raw,
  "learned_top_expected_pct":learned,
  "lift_pct":round((learned or 0)-(raw or 0),3),
  "raw_top_strong_rate":raw_strong,
  "learned_top_strong_rate":learned_strong,
  "raw_top_win_rate":raw_win,
  "learned_top_win_rate":learned_win,
  "raw_top_false_rate":raw_false,
  "learned_top_false_rate":learned_false,
  "h1_expected_pct":avg(9),
  "h3_expected_pct":avg(10),
  "h5_expected_pct":avg(11),
  "h10_expected_pct":avg(12),
  "h15_expected_pct":avg(13)
}

def _group(rows,key):
 groups={}
 for r in rows:
  if key=="symbol_option":g=f"{r[0]} {r[1]}"
  elif key=="score_bucket":g=_bucket(r[2])
  elif key=="symbol":g=r[0]
  else:g=r[1]
  groups.setdefault(g,[]).append(r)
 return {g:_metrics(v) for g,v in sorted(groups.items()) if len(v)>=MIN_GROUP_SAMPLES}

def report(path=DB_PATH):
 rows=_valid_rows(path)
 return {"leakage_safe":True,"total_valid":len(rows),"overall":_metrics(rows),"by_symbol_option":_group(rows,"symbol_option"),"by_score_bucket":_group(rows,"score_bucket"),"by_symbol":_group(rows,"symbol"),"by_option_type":_group(rows,"option_type")}

def main():
 print(json.dumps(report(),separators=(",",":"),sort_keys=True))
if __name__=="__main__":main()
