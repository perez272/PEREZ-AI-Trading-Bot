import pandas as pd
import pytest

from src.short_covering_filter import ShortCoveringFilter


def frames(prev_oi=True):
    current = {
        "Strike": [23000, 23100, 23200],
        "Type": ["CE", "CE", "PE"],
        "OI": [780, 900, 1200],
        "LTP": [150, 110, 80],
        "Volume": [3000, 1000, 900],
    }
    if prev_oi:
        current["Prev_OI"] = [1000, 900, 1200]
    historical = {
        "Strike": [23000, 23100, 23200],
        "Type": ["CE", "CE", "PE"],
        "OI": [1000, 1000, 1200],
        "LTP": [100, 100, 80],
        "Volume": [1000, 1000, 900],
    }
    return pd.DataFrame(current), pd.DataFrame(historical)


def test_detects_intraday_short_covering_evidence():
    current, historical = frames(prev_oi=False)
    current["OI_Prev_Snapshot"] = [1000, 900, 1200]
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert bool(row["Baseline_Candidate"])
    assert row["OI_Reference"] == "previous_session_oi"
    assert row["OI_Pct_Change"] == pytest.approx(-22.0)
    assert row["Price_Pct_Change"] == pytest.approx(50.0)
    assert row["Volume_Ratio"] == pytest.approx(3.0)
    assert row["Signal_Interpretation"] == "PREVIOUS_SESSION_OI_BASELINE_ONLY"


def test_historical_oi_fallback_is_explicitly_labelled():
    current, historical = frames(prev_oi=False)
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert bool(row["Baseline_Candidate"])
    assert row["OI_Reference"] == "historical_ma"
    assert row["Signal_Interpretation"] == "HISTORICAL_OI_BASELINE_DEVIATION_ONLY"


def test_no_signal_when_thresholds_not_all_met():
    current, historical = frames()
    current.loc[0, "Volume"] = 1000
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    assert not bool(result.loc[0, "Signal"])


def test_invalid_zero_baseline_is_rejected_as_data_quality():
    current, historical = frames()
    historical.loc[0, "Volume"] = 0
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert row["Data_Quality"] == "INVALID_OR_MISSING_BASELINE"


def test_duplicate_contract_keys_fail_closed():
    current, historical = frames()
    current = pd.concat([current, current.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        ShortCoveringFilter().analyze_option_chain(current, historical)


def test_missing_historical_contract_does_not_signal():
    current, historical = frames()
    historical = historical.iloc[1:].copy()
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert row["Data_Quality"] == "NO_HISTORICAL_MATCH"


def test_invalid_configuration_fails_fast():
    with pytest.raises(ValueError):
        ShortCoveringFilter(oi_drop_threshold=10)



def test_invalid_previous_oi_does_not_fall_back_to_historical_ma():
    current, historical = frames()
    current.loc[0, "Prev_OI"] = 0
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert row["OI_Reference"] == "invalid_previous_oi"
    assert row["Data_Quality"] == "INVALID_OR_MISSING_BASELINE"


def test_negative_current_oi_or_volume_fails_closed():
    current, historical = frames()
    current.loc[0, "OI"] = -10
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert not bool(row["Signal"])
    assert row["Data_Quality"] == "INVALID_OR_MISSING_BASELINE"


def test_strike_numeric_representation_matches():
    current, historical = frames(prev_oi=False)
    current["OI_Prev_Snapshot"] = [1000, 900, 1200]
    current["Strike"] = current["Strike"].astype(str)
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    assert len(result) == 3
    assert bool(result.loc[result["Strike"].eq(23000), "Signal"].iloc[0])



def test_explicit_previous_snapshot_oi_can_confirm_intraday_evidence():
    current, historical = frames(prev_oi=False)
    current["OI_Prev_Snapshot"] = [1000, 900, 1200]
    result = ShortCoveringFilter().analyze_option_chain(current, historical)
    row = result.loc[result["Strike"].eq(23000)].iloc[0]
    assert bool(row["Signal"])
    assert row["OI_Reference"] == "previous_snapshot"
    assert row["Signal_Interpretation"] == "INTRADAY_OI_REDUCTION_EVIDENCE"
