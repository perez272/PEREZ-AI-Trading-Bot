"""Forward-outcome learning for Tier-1 surge events.
Detection features are frozen at detection time. Outcomes use only later quotes
inside the 15.5-minute observation window, with the first valid quote at or after
each horizon used as that horizon's reference. This avoids missed narrow polling
windows while preventing future-data leakage.
Advisory only: never changes risk or order controls.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH=Path("data/memory/adaptive_trade_memory.sqlite3")
HORIZONS=(1,3,5,10,15)
HORIZON_TOLERANCE_MIN=0.5


def _db(path=DB_PATH):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(p);c.execute("PRAGMA journal_mode=WAL");return c


def _epoch(ts):
    if not ts:return None
    try:return datetime.fromisoformat(str(ts).replace("Z","+00:00")).timestamp()
    except (TypeError,ValueError):return None


def _pct(price,entry):
    return ((float(price)-float(entry))/float(entry)*100.0) if float(entry)>0 else 0.0


def _init(path=DB_PATH):
    with _db(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS surge_candidates(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,option_type TEXT NOT NULL,instrument_key TEXT NOT NULL,expiry TEXT,strike REAL,detection_ts TEXT NOT NULL,entry_ltp REAL NOT NULL,score REAL,features_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'UNRESOLVED',source TEXT NOT NULL DEFAULT 'live')")
        db.execute("CREATE TABLE IF NOT EXISTS surge_outcomes(candidate_id INTEGER PRIMARY KEY,h1_ltp REAL,h3_ltp REAL,h5_ltp REAL,h10_ltp REAL,h15_ltp REAL,mfe_pct REAL NOT NULL DEFAULT 0,mae_pct REAL NOT NULL DEFAULT 0,continuation_pct REAL,reversal_pct REAL,label TEXT NOT NULL DEFAULT 'UNRESOLVED',resolved_ts TEXT,FOREIGN KEY(candidate_id) REFERENCES surge_candidates(id))")
        db.execute("CREATE INDEX IF NOT EXISTS idx_surge_candidates_instrument_ts ON surge_candidates(instrument_key,detection_ts)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_surge_candidates_status ON surge_candidates(status)")


def _feature_copy(event):
    nested=event.get("features") if isinstance(event.get("features"),dict) else {}
    f=dict(nested)
    keys=("symbol","option_type","instrument_key","contract","expiry","strike","move_pct","move_1m_pct","move_3m_pct","move_5m_pct","velocity","acceleration","velocity_pct_per_min","acceleration_pct_per_min2","volume_ratio","spread_pct","volume","oi","iv","delta","gamma","theta","vega","regime","movement_bucket","momentum_bucket","trend_bucket","volume_bucket","oi_bucket","spread_bucket","mtf","source","score")
    for k in keys:
        if k in event and event.get(k) is not None:f[k]=event.get(k)
    return {k:v for k,v in f.items() if v is not None}


def _bucket(value,edges):
    try:x=float(value)
    except (TypeError,ValueError):return "UNKNOWN"
    for label,limit in edges:
        if x<limit:return label
    return edges[-1][0]


def _learning_features(features):
    f=dict(features or {})
    return {
        "symbol":f.get("symbol","UNKNOWN"),"option_type":f.get("option_type","UNKNOWN"),
        "move_bucket":_bucket(f.get("move_5m_pct",f.get("move_pct")),[("<1",1),("1-2",2),("2-4",4),("4-8",8),("8+",10**9)]),
        "momentum_bucket":_bucket(f.get("velocity",f.get("velocity_pct_per_min")),[("<0",0),("0-0.5",0.5),("0.5-1",1),("1-2",2),("2+",10**9)]),
        "acceleration_bucket":_bucket(f.get("acceleration",f.get("acceleration_pct_per_min2")),[("<0",0),("0-0.5",0.5),("0.5-1",1),("1+",10**9)]),
        "volume_bucket":_bucket(f.get("volume_ratio"),[("<1",1),("1-1.5",1.5),("1.5-3",3),("3+",10**9)]),
        "spread_bucket":_bucket(f.get("spread_pct"),[("<1",1),("1-2",2),("2-5",5),("5+",10**9)]),
        "score_bucket":_bucket(f.get("score"),[("<60",60),("60-70",70),("70-80",80),("80+",10**9)]),
        "regime":f.get("regime","UNKNOWN"),"mtf":f.get("mtf","UNKNOWN")
    }


def pattern_key(features):
    context=_learning_features(features)
    return hashlib.sha256(json.dumps(context,sort_keys=True,default=str).encode()).hexdigest()[:24]


def remember_surge(event,event_key=None,path=DB_PATH):
    _init(path);key=str(event_key or event.get("event_key") or "");instrument=str(event.get("instrument_key") or "");ts=str(event.get("detection_ts") or event.get("observed_ts") or "")
    try:ltp=float(event.get("ltp") or 0)
    except (TypeError,ValueError):ltp=0
    if not key or not instrument or not ts or ltp<=0:return 0
    raw=_feature_copy(event);context=_learning_features(raw);f={**raw,"learning_context":context,"pattern_key":pattern_key(raw)}
    with _db(path) as db:
        db.execute("INSERT OR IGNORE INTO surge_candidates(event_key,symbol,option_type,instrument_key,expiry,strike,detection_ts,entry_ltp,score,features_json,status,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(key,str(event.get("symbol") or raw.get("symbol") or ""),str(event.get("option_type") or raw.get("option_type") or ""),instrument,event.get("expiry",raw.get("expiry")),event.get("strike",raw.get("strike")),ts,ltp,float(event.get("score") or raw.get("score") or 0),json.dumps(f,separators=(",",":"),default=str),"UNRESOLVED","live"))
        row=db.execute("SELECT id FROM surge_candidates WHERE event_key=?",(key,)).fetchone();return int(row[0]) if row else 0


def _apply_quotes(db,quotes):
    changed=0
    for instrument_key,observed_ts,price in quotes:
        now=_epoch(observed_ts)
        if not instrument_key or price<=0 or now is None:continue
        rows=db.execute("SELECT id,detection_ts,entry_ltp FROM surge_candidates WHERE instrument_key=? AND status='UNRESOLVED'",(instrument_key,)).fetchall()
        for cid,dts,entry in rows:
            det=_epoch(dts)
            if det is None or now<=det or entry<=0:continue
            age=(now-det)/60.0
            if age>15.0+HORIZON_TOLERANCE_MIN:continue
            out=db.execute("SELECT h1_ltp,h3_ltp,h5_ltp,h10_ltp,h15_ltp,mfe_pct,mae_pct FROM surge_outcomes WHERE candidate_id=?",(cid,)).fetchone()
            if out is None:out=(None,None,None,None,None,0.0,0.0);db.execute("INSERT OR IGNORE INTO surge_outcomes(candidate_id) VALUES(?)",(cid,))
            vals=list(out);fp=_pct(price,entry);vals[5]=max(float(vals[5] or 0),fp);vals[6]=min(float(vals[6] or 0),fp)
            for i,h in enumerate(HORIZONS):
                if vals[i] is None and age>=h:vals[i]=price
            label=None
            if vals[4] is not None:
                final=_pct(vals[4],entry);mfe=float(vals[5] or 0);mae=float(vals[6] or 0)
                if mfe>=15 and final>=5:label="STRONG_WIN"
                elif final>=5 or mfe>=10:label="WIN"
                elif final<=-5 or mae<=-10:label="FALSE_SURGE"
                else:label="FLAT"
            db.execute("UPDATE surge_outcomes SET h1_ltp=?,h3_ltp=?,h5_ltp=?,h10_ltp=?,h15_ltp=?,mfe_pct=?,mae_pct=?,continuation_pct=?,reversal_pct=?,label=?,resolved_ts=? WHERE candidate_id=?",(vals[0],vals[1],vals[2],vals[3],vals[4],round(vals[5],2),round(vals[6],2),_pct(vals[2],entry) if vals[2] is not None else None,round(min(0.0,float(vals[6] or 0)),2),label or "UNRESOLVED",observed_ts if label else None,cid))
            if label:db.execute("UPDATE surge_candidates SET status='RESOLVED' WHERE id=?",(cid,));changed+=1
    return changed


def record_quotes(quotes,path=DB_PATH):
    _init(path);clean=[]
    for q in quotes:
        try:price=float(q[2] or 0)
        except (TypeError,ValueError):continue
        clean.append((str(q[0] or ""),str(q[1] or ""),price))
    with _db(path) as db:return _apply_quotes(db,clean)


def record_quote(instrument_key,observed_ts,ltp,path=DB_PATH):return record_quotes([(instrument_key,observed_ts,ltp)],path)


def backfill_existing_surge_candidates(source_db="data/memory/tier1_option_moves.sqlite3",path=DB_PATH):
    _init(path);src=Path(source_db)
    if not src.exists():return 0
    with sqlite3.connect(src) as s,_db(path) as db:
        rows=s.execute("SELECT event_key,symbol,option_type,instrument_key,expiry,strike,ltp,score,move_1m_pct,move_3m_pct,move_5m_pct,velocity,acceleration,volume_ratio,spread_pct,reasons_json,features_json,observed_ts,detection_ts FROM early_events").fetchall();added=0
        for r in rows:
            if not r[0] or not r[3] or not r[6] or not r[18]:continue
            try:f=json.loads(r[17]) if r[17] else {}
            except (TypeError,ValueError,json.JSONDecodeError):f={}
            f.update({"symbol":r[1],"option_type":r[2],"move_1m_pct":r[8],"move_3m_pct":r[9],"move_5m_pct":r[10],"velocity":r[11],"acceleration":r[12],"volume_ratio":r[13],"spread_pct":r[14],"score":r[7]});f["learning_context"]=_learning_features(f);f["pattern_key"]=pattern_key(f)
            cur=db.execute("INSERT OR IGNORE INTO surge_candidates(event_key,symbol,option_type,instrument_key,expiry,strike,detection_ts,entry_ltp,score,features_json,status,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(r[0],r[1],r[2],r[3],r[4],r[5],r[18],float(r[6]),float(r[7] or 0),json.dumps(f,separators=(",",":"),default=str),"UNRESOLVED","historical"));added+=cur.rowcount
        return added


def stats(path=DB_PATH):
    _init(path)
    with _db(path) as db:
        total=db.execute("SELECT COUNT(*) FROM surge_candidates").fetchone()[0];resolved=db.execute("SELECT COUNT(*) FROM surge_candidates WHERE status='RESOLVED'").fetchone()[0];labels=dict(db.execute("SELECT label,COUNT(*) FROM surge_outcomes GROUP BY label").fetchall());return {"candidates":int(total),"resolved":int(resolved),"unresolved":int(total-resolved),"labels":labels}


def _score_from_metrics(win_rate,false_rate,strong_rate,expected_pct):
    """Convert historical outcome quality into a bounded advisory adjustment.
    Uses both classification quality and forward 15m expectancy so a pattern
    cannot look good merely because it has many small wins.
    """
    quality=(win_rate+0.5*strong_rate-false_rate)*4.0
    expectancy=max(-4.0,min(4.0,float(expected_pct or 0.0)))
    return max(-8.0,min(8.0,quality+expectancy))


def _prediction(rows):
    labels=[r[0] for r in rows]
    n=len(labels)
    strong=labels.count("STRONG_WIN");wins=labels.count("WIN");false=labels.count("FALSE_SURGE")
    return strong/n,wins/n,false/n


def learning_signal(event,min_samples=10,path=DB_PATH):
    _init(path);raw=_feature_copy(event);pk=pattern_key(raw);context=_learning_features(raw)
    with _db(path) as db:
        exact=db.execute("SELECT o.label,c.entry_ltp,o.h15_ltp FROM surge_outcomes o JOIN surge_candidates c ON c.id=o.candidate_id WHERE o.label!='UNRESOLVED' AND json_extract(c.features_json,'$.pattern_key')=?",(pk,)).fetchall()
        exact_n=len(exact)
        if exact_n>=min_samples:
            strong_rate,wins_rate,false_rate=_prediction([(x[0],) for x in exact])
            returns=[_pct(x[2],x[1]) for x in exact if x[2] is not None and x[1]]
            expected=sum(returns)/len(returns) if returns else 0.0
            adj=_score_from_metrics(wins_rate,false_rate,strong_rate,expected)
            return {"status":"LEARNED","adjustment":round(adj,2),"confidence":round(min(1,exact_n/50),2),"samples":exact_n,"match":"EXACT","win_rate":round(wins_rate,3),"strong_rate":round(strong_rate,3),"false_surge_rate":round(false_rate,3),"expected_return_pct":round(expected,3)}
        rows=db.execute("SELECT o.label,c.features_json,c.entry_ltp,o.h15_ltp FROM surge_outcomes o JOIN surge_candidates c ON c.id=o.candidate_id WHERE o.label!='UNRESOLVED' AND c.symbol=? AND c.option_type=?",(context["symbol"],context["option_type"])).fetchall()
    weighted=[]
    for label,raw_json,entry,h15 in rows:
        try:old=json.loads(raw_json);oldctx=old.get("learning_context") or _learning_features(old)
        except (TypeError,ValueError,json.JSONDecodeError):continue
        same=sum(oldctx.get(k)==context.get(k) for k in ("move_bucket","momentum_bucket","acceleration_bucket","volume_bucket","spread_bucket","score_bucket","regime","mtf"))
        weight=0.5+same/8.0
        weighted.append((label,weight,entry,h15))
    effective=sum(w for _,w,_,_ in weighted)
    if effective>=min_samples:
        strong=sum(w for label,w,_,_ in weighted if label=="STRONG_WIN")/effective
        wins=sum(w for label,w,_,_ in weighted if label=="WIN")/effective
        false=sum(w for label,w,_,_ in weighted if label=="FALSE_SURGE")/effective
        returns=[_pct(h15,entry) for _,_,entry,h15 in weighted if h15 is not None and entry]
        expected=sum(returns)/len(returns) if returns else 0.0
        adj=_score_from_metrics(wins,false,strong,expected)
        return {"status":"LEARNED","adjustment":round(adj,2),"confidence":round(min(1,effective/50),2),"samples":round(effective,1),"match":"GENERALIZED","win_rate":round(wins,3),"strong_rate":round(strong,3),"false_surge_rate":round(false,3),"expected_return_pct":round(expected,3)}
    return {"status":"COLD_START","adjustment":0.0,"confidence":0.0,"samples":exact_n,"match":"EXACT","win_rate":0.0,"strong_rate":0.0,"false_surge_rate":0.0,"expected_return_pct":0.0}


_init()
