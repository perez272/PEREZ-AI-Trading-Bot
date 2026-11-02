import pytest

from src.capital_manager import get_paper_capital


def test_paper_capital_defaults_to_micro_account(monkeypatch):
    monkeypatch.delenv("PAPER_CAPITAL", raising=False)
    assert get_paper_capital() == 5000.0


def test_paper_capital_uses_explicit_configuration(monkeypatch):
    monkeypatch.setenv("PAPER_CAPITAL", "5000")
    assert get_paper_capital() == 5000.0


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_paper_capital_rejects_unsafe_values(monkeypatch, value):
    monkeypatch.setenv("PAPER_CAPITAL", value)
    with pytest.raises(RuntimeError):
        get_paper_capital()
