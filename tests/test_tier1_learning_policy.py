from src.tier1_option_observer import MOVE_THRESHOLDS


def test_learning_milestones_include_requested_levels():
    for level in (5.0, 10.0, 50.0, 100.0, 150.0):
        assert level in MOVE_THRESHOLDS


def test_100_percent_is_not_final_milestone():
    assert MOVE_THRESHOLDS.index(150.0) > MOVE_THRESHOLDS.index(100.0)
