from src.elcid_scanner import scan_elcid
from src.scan_telemetry import build_scan_report


def test_elcid_stage_is_read_only_and_full_portfolio():
    result = scan_elcid()
    assert result["stage"] == "ELCID"
    assert result["mode"] == "READ_ONLY"
    assert result["orders_enabled"] is False
    names = {item["name"] for item in result["categories"]}
    assert "Asian Paints" in names
    assert len(names) >= 8


def test_scan_report_is_one_consolidated_message():
    shares = [
        {
            "symbol": "TEST",
            "status": "OK",
            "score": 80,
            "close": 100.0,
            "rsi": 55.0,
            "signal": "BUY CE",
            "trend": "UP",
            "age_minutes": 1.0,
        },
        {"symbol": "STALE", "status": "STALE_OR_INVALID", "age_minutes": 9.0},
    ]
    options = [
        {"symbol": "TEST", "option_type": "CE", "options_score": 70, "ltp": 10.0, "paper_trade_candidate": False}
    ]
    elcid = scan_elcid()
    report = build_scan_report(shares, options, elcid, 1)
    assert report.count("🤖 PEREZ AI — SCAN #1") == 1
    assert "TOP SHARES" in report
    assert "TOP OPTIONS" in report
    assert "ELCID — SEPARATE READ-ONLY STAGE" in report
    assert "STALE_OR_INVALID=1" in report
    assert "NO REAL ORDERS" in report
