import sqlite3
from datetime import datetime,timezone,timedelta
from src.surge_outcome_learning import remember_surge
from src.shadow_diagnostics import report

def test_shadow_report_groups_and_blocks_future_ranking(tmp_path):
 db=tmp_path/"adaptive.sqlite3";base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
 for i in range(6):
  key=f"E{i}"
  remember_surge({"event_key":key,"symbol":"NIFTY","option_type":"CE","instrument_key":f"X{i}","ltp":100,"score":70,"detection_ts":base.isoformat(),"features":{"symbol":"NIFTY","option_type":"CE","score":70}},path=db)
  with sqlite3.connect(db) as c:
   c.execute("INSERT INTO surge_outcomes(candidate_id,h15_ltp,label,resolved_ts) SELECT id,105,'WIN',? FROM surge_candidates WHERE event_key=?",((base+timedelta(minutes=15)).isoformat(),key))
   c.execute("INSERT INTO surge_shadow_rankings(event_key,raw_score,learned_score,created_ts) VALUES(?,?,?,?)",(key,70,75,(base+timedelta(seconds=2)).isoformat()))
 r=report(db);assert r["leakage_safe"] is True;assert r["total_valid"]==6;assert r["by_symbol_option"]["NIFTY CE"]["samples"]==6

def test_shadow_report_excludes_ranking_after_resolution(tmp_path):
 db=tmp_path/"adaptive.sqlite3";base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
 remember_surge({"event_key":"LATE","symbol":"BANKNIFTY","option_type":"PE","instrument_key":"X","ltp":100,"score":80,"detection_ts":base.isoformat()},path=db)
 with sqlite3.connect(db) as c:
  c.execute("INSERT INTO surge_outcomes(candidate_id,h15_ltp,label,resolved_ts) SELECT id,90,'FALSE_SURGE',? FROM surge_candidates WHERE event_key='LATE'",((base+timedelta(minutes=15)).isoformat(),))
  c.execute("INSERT INTO surge_shadow_rankings VALUES(?,?,?,?)",("LATE",80,85,(base+timedelta(minutes=16)).isoformat()))
 assert report(db)["total_valid"]==0
