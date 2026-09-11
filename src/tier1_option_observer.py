"""Continuous Tier-1 option-chain observer and persistent move learner.
Observational only: never places or forces a trade.
"""
from __future__ import annotations
import hashlib,json,os,sqlite3,time
from collections import defaultdict,deque
from datetime import datetime,timezone
from pathlib import Path
from src.alternative_market_data import get_upstox_client
from src.explosive_move_detector import ExplosiveMoveSignal,detect_explosive_move
from src.surge_outcome_learning import backfill_existing_surge_candidates,remember_surge,record_quotes
TIER1_SYMBOLS=("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","NIFTYNXT50");MOVE_THRESHOLDS=(5.0,10.0,15.0,20.0,30.0,40.0,50.0,75.0,100.0);MEMORY_PATH=Path(os.getenv("TIER1_OPTION_MEMORY","data/memory/tier1_option_moves.sqlite3"));BASELINE_TTL_SECONDS=int(os.getenv("TIER1_OPTION_BASELINE_TTL_SECONDS","900"));CHAIN_REFRESH_TTL_SECONDS=int(os.getenv("TIER1_OPTION_CHAIN_REFRESH_TTL_SECONDS","15"));MAX_MEMORY_ROWS=int(os.getenv("TIER1_OPTION_MAX_MEMORY_ROWS","50000"));HISTORY_POINTS=30
class Tier1OptionObserver:
 def __init__(self,db_path:Path=MEMORY_PATH):
  self.db_path=Path(db_path);self.db_path.parent.mkdir(parents=True,exist_ok=True);self._history=defaultdict(lambda:deque(maxlen=HISTORY_POINTS));self._chain_cache={};self._init_db()
  try:
   added=backfill_existing_surge_candidates(self.db_path)
   if added:print(f"[SURGE LEARNING] imported {added} historical surge candidates (outcomes intentionally unresolved)")
  except Exception as exc:print(f"[SURGE LEARNING] historical import skipped safely: {exc}")
 def _connect(self):
  conn=sqlite3.connect(self.db_path);conn.execute("PRAGMA journal_mode=WAL");return conn
 def _init_db(self):
  with self._connect() as db:
   db.execute("CREATE TABLE IF NOT EXISTS baselines(contract_key TEXT PRIMARY KEY,symbol TEXT NOT NULL,option_type TEXT,expiry TEXT,strike REAL,baseline_ltp REAL NOT NULL,baseline_ts TEXT NOT NULL,last_ltp REAL NOT NULL,last_ts TEXT NOT NULL)");db.execute("CREATE TABLE IF NOT EXISTS move_events(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,option_type TEXT,contract TEXT,expiry TEXT,strike REAL,threshold REAL NOT NULL,baseline_ltp REAL NOT NULL,ltp REAL NOT NULL,move_pct REAL NOT NULL,observed_ts TEXT NOT NULL,features_json TEXT NOT NULL)");db.execute("CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,observed_ts TEXT NOT NULL,contracts_seen INTEGER NOT NULL,events_count INTEGER NOT NULL DEFAULT 0)");db.execute("CREATE INDEX IF NOT EXISTS idx_move_symbol_threshold ON move_events(symbol,threshold)");db.execute("CREATE TABLE IF NOT EXISTS early_events(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,option_type TEXT NOT NULL,instrument_key TEXT NOT NULL,expiry TEXT,strike REAL,ltp REAL NOT NULL,score REAL NOT NULL,move_1m_pct REAL,move_3m_pct REAL,move_5m_pct REAL,velocity REAL,acceleration REAL,volume_ratio REAL,spread_pct REAL,reasons_json TEXT NOT NULL,features_json TEXT NOT NULL,observed_ts TEXT NOT NULL,detection_ts TEXT NOT NULL,consumed INTEGER NOT NULL DEFAULT 0)");db.execute("CREATE INDEX IF NOT EXISTS idx_early_events_pending ON early_events(consumed,observed_ts)");db.execute("CREATE TABLE IF NOT EXISTS observer_meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL)");existing=db.execute("SELECT value FROM observer_meta WHERE key='surge_events_total'").fetchone()
   if existing is None:db.execute("INSERT INTO observer_meta(key,value) VALUES('surge_events_total',?)",(db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0],))
   db.execute("CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations(observed_ts)")
 @staticmethod
 def _contract_key(symbol,row,option_type):
  return hashlib.sha256("|".join(str(x or "") for x in (symbol,option_type,row.get("instrument_key"),row.get("expiry"),row.get("strike_price"))).encode()).hexdigest()
 @staticmethod
 def _market(row,option_type):return row.get("call_options" if option_type=="CE" else "put_options") or {}
 def _features(self,symbol,option_type,row,market,move_pct,baseline):
  md=market.get("market_data") or {};greeks=market.get("option_greeks") if isinstance(market.get("option_greeks"),dict) else {};return {"symbol":symbol,"option_type":option_type,"instrument_key":market.get("instrument_key"),"contract":market.get("trading_symbol") or row.get("trading_symbol"),"expiry":row.get("expiry"),"strike":row.get("strike_price"),"move_pct":round(move_pct,4),"baseline_ltp":round(baseline,4),"ltp":md.get("ltp"),"bid":md.get("bid_price"),"ask":md.get("ask_price"),"volume":md.get("volume"),"oi":md.get("oi"),"iv":greeks.get("iv"),"delta":greeks.get("delta"),"gamma":greeks.get("gamma"),"theta":greeks.get("theta"),"vega":greeks.get("vega")}
 def _record_fast_signal(self,symbol,option_type,market,observed_ts):
  key=str(market.get("instrument_key") or "");
  if not key:return None
  snapshot=dict(market);snapshot["observed_ts"]=observed_ts;signal=detect_explosive_move(symbol,option_type,snapshot,list(self._history[key]));self._history[key].append(snapshot);return signal
 def observe(self,symbol,chain,observed_ts=None):
  if symbol not in TIER1_SYMBOLS:raise ValueError(f"Tier-1 observer rejected non-Tier-1 symbol: {symbol}")
  observed_ts=observed_ts or datetime.now(timezone.utc).isoformat();now_epoch=time.time();events=[];valid_contracts=0
  quote_batch=[]
  for row in chain or []:
   for option_type in ("CE","PE"):
    market=self._market(row,option_type);md=market.get("market_data") or {}
    try:ltp=float(md.get("ltp",0) or 0)
    except (TypeError,ValueError):continue
    if ltp>0 and market.get("instrument_key"):quote_batch.append((market.get("instrument_key"),observed_ts,ltp))
  try:record_quotes(quote_batch)
  except Exception as exc:print(f"[SURGE LEARNING] batch quote update skipped: {exc}")
  with self._connect() as db:
   for row in chain or []:
    for option_type in ("CE","PE"):
     market=self._market(row,option_type);md=market.get("market_data") or {}
     try:ltp=float(md.get("ltp",0) or 0)
     except (TypeError,ValueError):continue
     if ltp<=0 or not market.get("instrument_key"):continue
     valid_contracts+=1;fast=self._record_fast_signal(symbol,option_type,market,observed_ts)
     if fast and fast.early:
      features=self._features(symbol,option_type,row,market,fast.move_5m_pct,fast.ltp);detection_ts=datetime.now(timezone.utc).isoformat();early_key=f"{fast.instrument_key}|EARLY|{observed_ts[:19]}";early_event={"type":"EARLY_EXPLOSIVE","symbol":symbol,"option_type":option_type,"score":fast.score,"move_1m_pct":fast.move_1m_pct,"move_3m_pct":fast.move_3m_pct,"move_5m_pct":fast.move_5m_pct,"velocity":fast.velocity_pct_per_min,"acceleration":fast.acceleration_pct_per_min2,"volume_ratio":fast.volume_ratio,"spread_pct":fast.spread_pct,"reasons":list(fast.reasons),"instrument_key":fast.instrument_key,"ltp":fast.ltp,"expiry":row.get("expiry"),"strike":row.get("strike_price"),"contract":features.get("contract"),"features":features,"observed_ts":observed_ts,"detection_ts":detection_ts}
      try:db.execute("INSERT INTO early_events(event_key,symbol,option_type,instrument_key,expiry,strike,ltp,score,move_1m_pct,move_3m_pct,move_5m_pct,velocity,acceleration,volume_ratio,spread_pct,reasons_json,features_json,observed_ts,detection_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(early_key,symbol,option_type,fast.instrument_key,row.get("expiry"),row.get("strike_price"),fast.ltp,fast.score,fast.move_1m_pct,fast.move_3m_pct,fast.move_5m_pct,fast.velocity_pct_per_min,fast.acceleration_pct_per_min2,fast.volume_ratio,fast.spread_pct,json.dumps(list(fast.reasons)),json.dumps(features,separators=(",",":")),observed_ts,detection_ts))
      except sqlite3.IntegrityError:pass
      try:remember_surge(early_event,early_key)
      except Exception as exc:print(f"[SURGE LEARNING] candidate persistence skipped: {exc}")
      events.append(early_event)
     key=self._contract_key(symbol,row,option_type);existing=db.execute("SELECT baseline_ltp,baseline_ts,last_ltp FROM baselines WHERE contract_key=?",(key,)).fetchone()
     if not existing:db.execute("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?)",(key,symbol,option_type,row.get("expiry"),row.get("strike_price"),ltp,observed_ts,ltp,observed_ts));continue
     baseline,baseline_ts,_=existing
     try:baseline_age=now_epoch-datetime.fromisoformat(baseline_ts).timestamp()
     except (ValueError,TypeError):baseline_age=BASELINE_TTL_SECONDS+1
     if baseline_age>BASELINE_TTL_SECONDS or ltp<baseline*0.5:db.execute("UPDATE baselines SET baseline_ltp=?,baseline_ts=?,last_ltp=?,last_ts=? WHERE contract_key=?",(ltp,observed_ts,ltp,observed_ts,key));continue
     move_pct=(ltp-baseline)/baseline*100.0
     for threshold in MOVE_THRESHOLDS:
      if move_pct<threshold:continue
      event_key=f"{key}|{threshold}|{observed_ts[:16]}";features=self._features(symbol,option_type,row,market,move_pct,baseline)
      try:db.execute("INSERT INTO move_events(event_key,symbol,option_type,contract,expiry,strike,threshold,baseline_ltp,ltp,move_pct,observed_ts,detection_ts,features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",(event_key,symbol,option_type,features.get("contract"),row.get("expiry"),row.get("strike_price"),threshold,baseline,ltp,move_pct,observed_ts,datetime.now(timezone.utc).isoformat(),json.dumps(features,separators=(",",":"))));db.execute("UPDATE observer_meta SET value=value+1 WHERE key='surge_events_total'");events.append({"type":"THRESHOLD","threshold":threshold,**features})
      except sqlite3.IntegrityError:pass
     db.execute("UPDATE baselines SET last_ltp=?,last_ts=? WHERE contract_key=?",(ltp,observed_ts,key))
   if valid_contracts:db.execute("INSERT INTO observations(symbol,observed_ts,contracts_seen,events_count) VALUES (?,?,?,?)",(symbol,observed_ts,valid_contracts,len(events)))
   db.execute("DELETE FROM move_events WHERE id NOT IN (SELECT id FROM move_events ORDER BY id DESC LIMIT ?)",(MAX_MEMORY_ROWS,))
  return events
 def observe_all(self):
  client=get_upstox_client()
  if not client.available():return []
  events=[];now=time.monotonic()
  for symbol in TIER1_SYMBOLS:
   try:
    cached=self._chain_cache.get(symbol)
    if cached and now-cached[0]<CHAIN_REFRESH_TTL_SECONDS:chain=cached[1];source="cache"
    else:chain=client.get_option_chain(symbol);self._chain_cache.__setitem__(symbol,(time.monotonic(),chain)) if chain else None;source="upstox"
    if chain and source=="upstox":events.extend(self.observe(symbol,chain,observed_ts=datetime.now(timezone.utc).isoformat()));print(f"[TIER1 OBSERVER] {symbol}: observation source={source}")
    elif chain:print(f"[TIER1 OBSERVER] {symbol}: cached snapshot — detector history unchanged")
   except Exception as exc:print(f"[TIER1 OBSERVER] {symbol}: {exc}")
  return events
 def get_pending_early_events(self,limit=10):
  with self._connect() as db:rows=db.execute("SELECT id,event_key,symbol,option_type,instrument_key,expiry,strike,ltp,score,move_1m_pct,move_3m_pct,move_5m_pct,velocity,acceleration,volume_ratio,spread_pct,reasons_json,features_json,observed_ts,detection_ts FROM early_events WHERE consumed=0 AND (julianday('now')-julianday(COALESCE(detection_ts,observed_ts)))*86400.0<=60 ORDER BY observed_ts DESC,id DESC LIMIT ?",(max(1,int(limit)),)).fetchall()
  fields=("id","event_key","symbol","option_type","instrument_key","expiry","strike","ltp","score","move_1m_pct","move_3m_pct","move_5m_pct","velocity","acceleration","volume_ratio","spread_pct","reasons_json","features_json","observed_ts","detection_ts");out=[]
  for row in rows:
   e=dict(zip(fields,row))
   try:e["reasons"]=json.loads(e.pop("reasons_json"))
   except (TypeError,ValueError,json.JSONDecodeError):e["reasons"]=[]
   try:e["features"]=json.loads(e.pop("features_json"))
   except (TypeError,ValueError,json.JSONDecodeError):e["features"]={}
   out.append(e)
  return out
 def mark_early_event_consumed(self,event_id):
  with self._connect() as db:db.execute("UPDATE early_events SET consumed=1 WHERE id=? AND consumed=0",(int(event_id),))
 def stats(self):
  with self._connect() as db:observations=db.execute("SELECT COUNT(*) FROM observations").fetchone()[0];surge_events=db.execute("SELECT COUNT(*) FROM move_events").fetchone()[0];total_row=db.execute("SELECT value FROM observer_meta WHERE key='surge_events_total'").fetchone();surge_events_total=int(total_row[0]) if total_row else int(surge_events)
  return {"observations":int(observations),"surge_events":int(surge_events),"surge_events_total":int(surge_events_total)}
 def match(self,symbol,features,threshold=None,limit=50):
  clauses=["symbol=?"];params=[symbol]
  if threshold is not None:clauses.append("threshold=?");params.append(float(threshold))
  with self._connect() as db:rows=db.execute(f"SELECT threshold,features_json FROM move_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",(*params,limit)).fetchall()
  if not rows:return {"matches":0,"confidence":0.0}
  numeric=("volume","oi","iv","delta","gamma","theta","vega","move_pct");scores=[]
  for _,raw in rows:
   try:
    old=json.loads(raw);comparable=[k for k in numeric if features.get(k) is not None and old.get(k) is not None]
    if not comparable:continue
    similarities=[]
    for k in comparable:
     a,b=float(features[k]),float(old[k]);scale=max(abs(a),abs(b),1e-9);similarities.append(max(0.0,1.0-abs(a-b)/scale))
    scores.append(sum(similarities)/len(similarities))
   except (TypeError,ValueError,json.JSONDecodeError):continue
  return {"matches":len(scores),"confidence":round(min(1.0,(sum(scores)/len(scores)) if scores else 0.0),4)}
_observer=Tier1OptionObserver()
def observe_tier1_option_chains():return _observer.observe_all()
def get_tier1_option_observer():return _observer
