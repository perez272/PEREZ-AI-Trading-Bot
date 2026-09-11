from datetime import datetime,timezone,timedelta
import sqlite3
from src.surge_outcome_learning import remember_surge,record_quote,stats,learning_signal

def _resolve(db,event_key,instrument,base,prices):
    event={"event_key":event_key,"symbol":"NIFTY","option_type":"CE","instrument_key":instrument,"ltp":100,"score":80,"detection_ts":base.isoformat(),"move_5m_pct":5.0,"velocity":1.0,"acceleration":0.8,"volume_ratio":2.0,"spread_pct":1.0}
    remember_surge(event,path=db)
    for mins,price in prices:
        record_quote(instrument,(base+timedelta(minutes=mins)).isoformat(),price,path=db)
    return event

def test_future_quotes_resolve_without_lookahead(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
    event={"event_key":"E1","symbol":"NIFTY","option_type":"CE","instrument_key":"NSE_FO|1","expiry":"2026-09-15","strike":25000,"ltp":100,"score":80,"detection_ts":base.isoformat(),"features":{"symbol":"NIFTY","option_type":"CE","move_5m_pct":5.0,"volume_ratio":2.0}}
    remember_surge(event,path=db)
    assert stats(db)["unresolved"]==1
    record_quote("NSE_FO|1",(base-timedelta(seconds=1)).isoformat(),200,path=db)
    assert stats(db)["resolved"]==0
    for mins,price in ((1,110),(3,125),(5,118),(10,130),(15,125)):
        record_quote("NSE_FO|1",(base+timedelta(minutes=mins)).isoformat(),price,path=db)
    assert stats(db)["resolved"]==1
    with sqlite3.connect(db) as c:
        row=c.execute("SELECT h1_ltp,h3_ltp,h5_ltp,h10_ltp,h15_ltp,mfe_pct,mae_pct,label FROM surge_outcomes").fetchone()
    assert row[:5]==(110.0,125.0,118.0,130.0,125.0)
    assert row[5]>=30.0 and row[6]==0.0 and row[7] in {"WIN","STRONG_WIN"}

def test_late_polling_still_captures_each_horizon(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
    event={"event_key":"LATE1","symbol":"NIFTY","option_type":"PE","instrument_key":"NSE_FO|2","ltp":100,"score":80,"detection_ts":base.isoformat(),"features":{"symbol":"NIFTY","option_type":"PE","move_5m_pct":6.0}}
    remember_surge(event,path=db)
    for mins,price in ((1.8,110),(3.7,120),(5.8,115),(10.7,130),(15.4,125)):
        record_quote("NSE_FO|2",(base+timedelta(minutes=mins)).isoformat(),price,path=db)
    assert stats(db)["resolved"]==1
    with sqlite3.connect(db) as c:
        row=c.execute("SELECT h1_ltp,h3_ltp,h5_ltp,h10_ltp,h15_ltp,label FROM surge_outcomes").fetchone()
    assert row[:5]==(110.0,120.0,115.0,130.0,125.0)
    assert row[5] in {"WIN","STRONG_WIN"}

def test_learning_is_cold_start_until_mature(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    event={"event_key":"E1","symbol":"NIFTY","option_type":"CE","instrument_key":"NSE_FO|1","ltp":100,"detection_ts":"2026-09-11T07:00:00+00:00","features":{"symbol":"NIFTY","option_type":"CE","move_5m_pct":5.0}}
    remember_surge(event,path=db)
    assert learning_signal(event,path=db)["status"]=="COLD_START"

def test_horizons_survive_sparse_polling(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
    event={"event_key":"sparse-test","symbol":"NIFTY","option_type":"CE","instrument_key":"TEST|1","detection_ts":base.isoformat(),"ltp":100.0,"score":80}
    remember_surge(event,"sparse-test",str(db))
    quotes=[("TEST|1",(base+timedelta(minutes=1,seconds=45)).isoformat(),102.0),("TEST|1",(base+timedelta(minutes=3,seconds=45)).isoformat(),104.0),("TEST|1",(base+timedelta(minutes=5,seconds=45)).isoformat(),106.0),("TEST|1",(base+timedelta(minutes=10,seconds=45)).isoformat(),108.0),("TEST|1",(base+timedelta(minutes=15,seconds=15)).isoformat(),110.0)]
    record_quotes(quotes,str(db))
    with sqlite3.connect(db) as c:row=c.execute("SELECT h1_ltp,h3_ltp,h5_ltp,h10_ltp,h15_ltp,label FROM surge_outcomes").fetchone()
    assert row[:5]==(102.0,104.0,106.0,108.0,110.0)
    assert row[5] in ("WIN","STRONG_WIN")

def test_top_level_features_are_preserved(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    event={"event_key":"TOP1","symbol":"BANKNIFTY","option_type":"CE","instrument_key":"TEST|TOP","ltp":100,"score":85,"detection_ts":"2026-09-11T07:00:00+00:00","move_5m_pct":7.0,"velocity":1.2,"acceleration":0.9,"volume_ratio":2.5,"spread_pct":1.2}
    remember_surge(event,path=db)
    with sqlite3.connect(db) as c:raw=c.execute("SELECT features_json FROM surge_candidates WHERE event_key='TOP1'").fetchone()[0]
    f=__import__('json').loads(raw)
    assert f["move_5m_pct"]==7.0 and f["volume_ratio"]==2.5 and f["pattern_key"]

def test_generalized_learning_can_mature_from_symbol_type(tmp_path):
    db=tmp_path/"adaptive.sqlite3"
    base=datetime(2026,9,11,7,0,tzinfo=timezone.utc)
    events=[]
    for i in range(10):
        e={"event_key":f"G{i}","symbol":"NIFTY","option_type":"CE","instrument_key":f"TEST|{i}","ltp":100,"score":80,"detection_ts":(base+timedelta(minutes=20*i)).isoformat(),"move_5m_pct":5.0,"velocity":1.0,"acceleration":0.8,"volume_ratio":2.0,"spread_pct":1.0}
        remember_surge(e,path=db)
        for mins,price in ((1,105),(3,106),(5,107),(10,108),(15,110)):
            record_quote(e["instrument_key"],(base+timedelta(minutes=20*i+mins)).isoformat(),price,path=db)
        events.append(e)
    result=learning_signal(events[-1],path=db)
    assert result["status"]=="LEARNED"
    assert result["samples"]>=10
    assert result["adjustment"]>0
