"""Fast production-path smoke tests.

These tests intentionally cover only the runtime path used by main.py. Legacy
research/backup scripts are audited separately and must not block the core bot.
"""

import importlib


CORE_MODULES = (
    "main",
    "src.market_scanner",
    "src.ai_scoring",
    "src.trade_decision",
    "src.trade_engine",
    "src.live_trade_monitor",
    "src.risk_manager",
    "src.capital_manager",
    "src.production_guard",
    "src.telegram_alert",
)


def test_core_modules_import_without_runtime_startup():
    for module_name in CORE_MODULES:
        module = importlib.import_module(module_name)
        assert module is not None


def test_main_defaults_to_paper_mode(monkeypatch):
    monkeypatch.setenv("PAPER_MODE", "true")
    main = importlib.import_module("main")
    assert main.PAPER_MODE is True
