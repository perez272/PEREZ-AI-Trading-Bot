"""Continuous Tier-1 option-chain observer with surge and expiry learning."""
from __future__ import annotations
import hashlib,json,os,sqlite3,time
from collections import defaultdict,deque
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from src.alternative_market_data import get_upstox_client
from src.explosive_move_detector import detect_explosive_move
from src.options_surge_engine import OptionsSurgeEngine
from src.expiry_learning_engine import record_surge_events
from src.move_memory import record_move
TIER1_SYMBOLS=("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","NIFTYNXT50","NIFTYFPI")
MOVE_THRESHOLDS=(5.0,10.0,15.0,20.0,30.0,40.0,50.0,75.0,100.0)
MEMORY_PATH=Path(os.getenv("TIER1_OPTION_MEMORY","data/memory/tier1_option_moves.sqlite3"))
BASELINE_TTL_SECONDS=int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS","900")); MAX_MEMORY_ROWS=int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS","50000")); HISTORY_POINTS=16
class Tier1OptionObserver:
 def __init__(self,db_path:Path=MEMORY_PATH):
  self.db_path=Path(db_path);self.db_path.parent.mkdir(parents=True,exist_ok=True);self._history=defaultdict(lambda:deque(maxlen=HISTORY_POINTS));self.surge_engine=OptionsSurgeEngine();self._init_db()
 def _connect(self):
  c=sqlite3.connect(self.db_path);c.execute("PRAGMA journal_mode=WAL");return c
 def _init_db(self):
  with self._connect() as db:
   db.execute("CREATE TABLE IF NOT EXISTS baselines (contract_key TEXT PRIMARY KEY,symbol TEXT NOT NULL,option_type TEXT,expiry TEXT,strike REAL,baseline_ltp REAL NOT NULL,baseline_ts TEXT NOT NULL,last_ltp REAL NOT NULL,last_ts TEXT NOT NULL)")
   db.execute("CREATE TABLE IF NOT EXISTS move_events (id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,option_type TEXT,contract TEXT,expiry TEXT,strike REAL,threshold REAL NOT NULL,baseline_ltp REAL NOT NULL,ltp REAL NOT NULL,move_pct REAL NOT NULL,observed_ts TEXT NOT NULL,features_json TEXT NOT NULL)")
   db.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,observed_ts TEXT NOT NULL,contracts_seen INTEGER NOT NULL,events_count INTEGER NOT NULL DEFAULT 0)")
 def observe(self,symbol:str,chain:list[dict[str,Any]],observed_ts:str|None=None):
  if symbol not in TIER1_SYMBOLS: raise ValueError(f"Tier-1 observer rejected non-Tier-1 symbol: {symbol}")
  observed_ts=observed_ts or datetime.now(timezone.utc).isoformat();events=[];valid=0;now=time.time()
  with self._connect() as db:
   for row in chain or []:
    for typ in ("CE","PE"):
     market=row.get("call_options" if typ=="CE" else "put_options") or {};md=market.get("market_data") or {}
     try: ltp=float(md.get("ltp",0) or 0)
     except (TypeError,ValueError): continue
     key=str(market.get("instrument_key") or "")
     if ltp<=0 or not key: continue
     valid+=1
     snap={"symbol":symbol,"option_type":typ,"instrument_key":key,"market_data":md,"option_greeks":market.get("option_greeks") or {},"observed_ts":observed_ts}
     fast=detect_explosive_move(symbol,typ,snap,list(self._history[key]));self._history[key].append(snap)
     if fast and fast.early: events.append({"type":"EARLY_EXPLOSIVE","symbol":symbol,"option_type":typ,"instrument_key":key,"current_ltp":fast.ltp,"move_1m_pct":fast.move_1m_pct,"move_3m_pct":fast.move_3m_pct,"move_5m_pct":fast.move_5m_pct,"score":fast.score,"observed_ts":observed_ts,"expiry":row.get("expiry")})
     surge=self.surge_engine.observe(snap)
     for e in surge:e["expiry"]=row.get("expiry");events.append({"type":"SURGE",**e})
     raw="|".join(str(x or "") for x in (symbol,typ,key,row.get("expiry"),row.get("strike_price")));ck=hashlib.sha256(raw.encode()).hexdigest()
     old=db.execute("SELECT baseline_ltp,baseline_ts FROM baselines WHERE contract_key=?",(ck,)).fetchone()
     if not old: db.execute("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?)",(ck,symbol,typ,row.get("expiry"),row.get("strike_price"),ltp,observed_ts,ltp,observed_ts));continue
     base,base_ts=old
     try: age=now-datetime.fromisoformat(base_ts).timestamp()
     except (ValueError,TypeError): age=BASELINE_TTL_SECONDS+1
     if age>BASELINE_TTL_SECONDS or ltp<base*.5: db.execute("UPDATE baselines SET baseline_ltp=?,baseline_ts=?,last_ltp=?,last_ts=? WHERE contract_key=?",(ltp,observed_ts,ltp,observed_ts,ck));continue
     move=(ltp-base)/base*100
     for threshold in MOVE_THRESHOLDS:
      if move>=threshold:
       features={"symbol":symbol,"option_type":typ,"instrument_key":key,"contract":market.get("trading_symbol"),"expiry":row.get("expiry"),"strike":row.get("strike_price"),"move_pct":round(move,4),"baseline_ltp":base,"ltp":ltp,"volume":md.get("volume"),"oi":md.get("oi"),"iv":(market.get("option_greeks") or {}).get("iv")};ek=f"{ck}|{threshold}|{observed_ts[:16]}"
       try: db.execute("INSERT INTO move_events(event_key,symbol,option_type,contract,expiry,strike,threshold,baseline_ltp,ltp,move_pct,observed_ts,features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(ek,symbol,typ,features["contract"],features["expiry"],features["strike"],threshold,base,ltp,move,observed_ts,json.dumps(features,separators=(",",":"))));events.append({"type":"THRESHOLD","threshold":threshold,**features})
       except sqlite3.IntegrityError: pass
     db.execute("UPDATE baselines SET last_ltp=?,last_ts=? WHERE contract_key=?",(ltp,observed_ts,ck))
   if valid: db.execute("INSERT INTO observations(symbol,observed_ts,contracts_seen,events_count) VALUES(?,?,?,?)",(symbol,observed_ts,valid,len(events)))
   db.execute("DELETE FROM move_events WHERE id NOT IN (SELECT id FROM move_events ORDER BY id DESC LIMIT ?)",(MAX_MEMORY_ROWS,))
  canonical=[e for e in events if e.get("type") in {"SURGE","THRESHOLD"}]
  if canonical:
   record_surge_events(canonical)
   for e in canonical:
    if e.get("type")=="THRESHOLD": record_move({**e,"percent_change":e.get("move_pct")})
  return events
 def observe_all(self):
  client=get_upstox_client()
  if not client.available(): return []
  events=[]
  for symbol in TIER1_SYMBOLS:
   try:
    chain=client.get_option_chain(symbol)
    if chain: events.extend(self.observe(symbol,chain))
   except Exception as exc: print(f"[TIER1 OBSERVER] {symbol}: {exc}")
  return events
 def stats(self):
  with self._connect() as db:return {"observations":db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],"surge_events":db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0]}
_observer=Tier1OptionObserver()
def observe_tier1_option_chains(): return _observer.observe_all()
def get_tier1_option_observer(): return _observer
