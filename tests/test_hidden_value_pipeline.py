from datetime import date, timedelta
from src.hidden_value_data_pipeline import build_candidates


def valid_row(**overrides):
    row = {
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
        "source_url": "https://www.nseindia.com/",
        "source_name": "NSE",
        "as_of_date": date.today().isoformat(),
    }
    row.update(overrides)
    return row


def test_pipeline_builds_valid_candidate():
    result = build_candidates([valid_row()])
    assert len(result) == 1
    assert result[0]["symbol"] == "TEST"
    assert result[0]["estimated_nav_cr"] == 1000.0
    assert result[0]["deferred_tax_cr"] == "10"
    assert result[0]["source_name"] == "NSE"


def test_pipeline_rejects_invalid_candidate():
    assert build_candidates([valid_row(shares_outstanding="0")]) == []


def test_pipeline_rejects_missing_provenance():
    assert build_candidates([valid_row(source_url="")]) == []


def test_pipeline_rejects_stale_data():
    stale = (date.today() - timedelta(days=401)).isoformat()
    assert build_candidates([valid_row(as_of_date=stale)]) == []
