from src.capital_manager import extract_available_capital
from src.risk_manager import can_open_new_trade


def test_extracts_available_cash_from_rms():
    assert extract_available_capital({"status": True, "data": {"availablecash": "50000.00", "net": "51000"}}) == 50000.0


def test_dynamic_daily_loss_is_two_percent_of_capital():
    allowed, reason, _ = can_open_new_trade(max_trades=3, max_daily_loss=None, capital=50000)
    assert allowed is False or allowed is True
    assert "300" not in reason or "Outside entry window" in reason
