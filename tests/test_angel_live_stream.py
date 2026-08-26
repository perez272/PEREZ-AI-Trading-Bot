from src.angel_live_stream import AngelLiveStream
from src.market_data_bus import get_tick, publish_tick


def test_bearer_prefix_is_normalized_once():
    assert AngelLiveStream._bearer("abc") == "Bearer abc"
    assert AngelLiveStream._bearer("Bearer abc") == "Bearer abc"
    assert AngelLiveStream._bearer("") == ""


def test_live_tick_bus_keeps_latest_tick():
    publish_tick({"token": "99926000", "last_traded_price": 12345})
    tick = get_tick("99926000")
    assert tick is not None
    assert tick["last_traded_price"] == 12345
