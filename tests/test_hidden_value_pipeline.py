from pathlib import Path
from src.hidden_value_data_pipeline import build_candidates


def test_pipeline_builds_valid_candidate():
    rows = [{
        "symbol": "TEST",
        "shares_outstanding": "200000",
        "market_price": "10000",
        "estimated_nav_cr": "1000",
        "listed_investments_cr": "800",
        "cash_cr": "50",
        "debt_cr": "20",
        "deferred_tax_cr": "10",
        "uncalled_commitment_cr": "5",
        "other_liabilities_cr": "5",
    }]
    result = build_candidates(rows)
    assert len(result) == 1
    assert result[0]["symbol"] == "TEST"
    assert result[0]["estimated_nav_cr"] == 1000.0


def test_pipeline_rejects_invalid_candidate():
    rows = [{"symbol": "BAD", "shares_outstanding": "0", "market_price": "100", "estimated_nav_cr": "100", "listed_investments_cr": "50"}]
    assert build_candidates(rows) == []
