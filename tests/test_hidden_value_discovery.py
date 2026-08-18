from pathlib import Path
from src.high_conviction_discovery import discover


def test_missing_or_empty_candidate_file_is_safe(tmp_path: Path):
    p = tmp_path / "hidden_value_candidates.csv"
    p.write_text("symbol,market_cap_cr,estimated_nav_cr,listed_investments_cr,corporate_action,regulatory_catalyst,special_auction,restructuring_event\n", encoding="utf-8")
    passed, rejected = discover(p)
    assert passed == []
    assert rejected == []


def test_missing_candidate_file_is_rejected(tmp_path: Path):
    passed, rejected = discover(tmp_path / "missing.csv")
    assert passed == []
    assert rejected[0]["reason"] == "CANDIDATE_FILE_MISSING"
