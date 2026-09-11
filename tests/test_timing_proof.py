from src.dashboard_telemetry import timing_proof


def _event(i, minute, pnl):
    key=f'E{i}'
    ts=f'2026-09-11T09:{minute:02d}:00+05:30'
    return [
        {'event_key':key,'stage':'PAPER_ENTRY','status':'OK','ts':ts,'symbol':'NIFTY','option_type':'CE','contract':'TEST','score':70,'details':{}},
        {'event_key':key,'stage':'OUTCOME','status':'OK','ts':ts,'symbol':'NIFTY','option_type':'CE','contract':'TEST','score':70,'details':{'pnl':pnl}},
    ]


def test_timing_proof_requires_minimum_evidence():
    rows=[]
    for i in range(10):
        rows += _event(i, 15+i, 10 if i % 2 == 0 else -5)
    result=timing_proof(rows)
    assert result['status']=='UNPROVEN'
    assert result['sample_count']==10
    assert result['minimum_samples']==30


def test_timing_proof_proves_only_after_sample_and_window_thresholds():
    rows=[]
    i=0
    for minute in (5, 35, 65):
        for _ in range(10):
            rows += _event(i, minute, 20 if i % 2 == 0 else -10)
            i += 1
    result=timing_proof(rows)
    assert result['status']=='PROVEN'
    assert result['proven'] is True
    assert result['sample_count']==30
    assert len(result['buckets'])==3
