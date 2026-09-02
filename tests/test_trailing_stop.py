from src.trade_monitor import monitor_trade

def trade():
    return {
        "symbol":"TEST","signal":"BUY CE","contract":"TEST",
        "exchange":"TEST","token":"TEST","entry":100.0,
        "quantity":10,"lots":1,"investment":1000.0,
        "stop_loss":98.0,"initial_stop_loss":98.0,
        "target1":104.0,"target2":107.0,
        "trailing_stop_pct":15.0,
    }

def test_high_watermark_trailing():
    t = trade()

    r = monitor_trade(t, 104.0)
    assert not r["closed"]

    r = monitor_trade(t, 200.0)
    assert r["high_watermark"] == 200.0
    assert r["stop_loss"] == 170.0

    r = monitor_trade(t, 250.0)
    assert r["high_watermark"] == 250.0
    assert r["stop_loss"] == 212.5

    r = monitor_trade(t, 230.0)
    assert r["stop_loss"] == 212.5

    r = monitor_trade(t, 212.5)
    assert r["closed"]
    assert r["exit_reason"] == "TRAILING_STOP"

def test_trailing_stop_moves_and_exits():
    t = trade()
    monitor_trade(t, 104.0)
    r = monitor_trade(t, 200.0)
    assert r["stop_loss"] == 170.0

    r = monitor_trade(t, 250.0)
    assert r["high_watermark"] == 250.0
    assert r["stop_loss"] == 212.5

    r = monitor_trade(t, 230.0)
    assert r["stop_loss"] == 212.5
    assert not r["closed"]

    r = monitor_trade(t, 212.5)
    assert r["closed"]
    assert r["exit_reason"] == "TRAILING_STOP"
