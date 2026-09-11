from datetime import datetime,timezone,timedelta
import sqlite3
from src.surge_outcome_learning import remember_surge,record_quote,stats,learning_signal

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
    # Deliberately miss the old +/-30s windows; these quotes are late but
    # still inside the 15.5-minute observation window.
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
