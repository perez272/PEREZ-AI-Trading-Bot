from src.elcid_scanner import scan_elcid
from src.scan_telemetry import build_scan_report


def test_elcid_stage_is_read_only_and_has_full_portfolio_categories():
    result = scan_elcid()
    assert result["stage"] == "ELCID"
    assert result["mode"] == "READ_ONLY"
    assert result["orders_enabled"] is False
    assert result["categories"]
    names = {item["name"] for item in result["categories"]}
    assert "Asian Paints" in names
    assert len(names) >= 2
    assert set(result["scenarios"]) == {"BULL", "BASE", "BEAR"}


def test_consolidated_report_contains_separate_stages_and_rejection_summary():
    shares = [
        {
            "symbol": "AAA",
            "status": "OK",
            "score": 82,
            "close": 100.0,
            "rsi": 61.2,
            "signal": "BUY CE",
            "trend": "UP",
            "age_minutes": 1.0,
        },
        {"symbol": "BBB", "status": "STALE"},
        {"symbol": "CCC", "status": "API_ERROR"},
    ]
    options = [
        {
            "symbol": "AAA",
            "option_type": "CE",
            "options_score": 76,
            "ltp": 12.5,
            "paper_trade_candidate": True,
        }
    ]
    elcid = {
        "ltp": 100000.0,
        "reported_nav_per_share": 400000.0,
        "market_discount_to_reported_nav_pct": 75.0,
        "categories": [{"name": "Asian Paints", "value_cr": 8794.0}, {"name": "Other quoted equity", "value_cr": 100.0}],
        "scenarios": {
            "BULL": {"nav_per_share": 500000.0},
            "BASE": {"nav_per_share": 400000.0},
            "BEAR": {"nav_per_share": 300000.0},
        },
    }

    report = build_scan_report(shares, options, elcid, 7)
    assert "SCAN #7" in report
    assert "TOP SHARES" in report
    assert "TOP OPTIONS" in report
    assert "ELCID — SEPARATE READ-ONLY STAGE" in report
    assert "Rejected summary:" in report
    assert "STALE=1" in report
    assert "API_ERROR=1" in report
    assert "NO REAL ORDERS" in report
    assert "Execution path unchanged" in report
    assert len(report) < 4096
