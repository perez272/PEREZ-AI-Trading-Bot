"""Repository-wide smoke and safety tests.

These tests deliberately avoid broker/network calls. Their job is to catch broken
imports, accidental live-order primitives, and unsafe default execution mode
before anything reaches EC2.
"""

import importlib
import pkgutil
from pathlib import Path

import src


ROOT = Path(__file__).resolve().parents[1]


def test_all_src_modules_import_without_side_effect_failure():
    failures = []
    for module_info in pkgutil.walk_packages(src.__path__, prefix="src."):
        try:
            importlib.import_module(module_info.name)
        except Exception as exc:  # pragma: no cover - assertion reports exact module
            failures.append(f"{module_info.name}: {type(exc).__name__}: {exc}")
    assert not failures, "Broken repository imports:\n" + "\n".join(failures)


def test_live_order_primitives_are_absent_from_runtime_code():
    forbidden = ("placeOrder", "placeOrderFullResponse", "modifyOrder", "cancelOrder")
    offenders = []
    for path in [ROOT / "main.py", *(ROOT / "src").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {token}")
    assert not offenders, "Live-order API primitive detected:\n" + "\n".join(offenders)


def test_paper_mode_is_the_safe_default():
    main = importlib.import_module("main")
    assert main.PAPER_MODE is True
