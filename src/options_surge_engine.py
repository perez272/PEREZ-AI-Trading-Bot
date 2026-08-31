"""Options surge detection engine for the PEREZ AI paper-trading pipeline.

This module is observational only. It never places orders and does not bypass
scanner, option, capital, or risk gates.  It provides a stable API around the
existing low-latency explosive-move detector so legacy imports remain valid.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.explosive_move_detector import ExplosiveMoveSignal, detect_explosive_move

SURGE_THRESHOLDS_PCT = (5.0, 10.0, 15.0)


def detect_surge(
    symbol: str,
    option_type: str,
    current: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a normalized surge observation, or None when evidence is insufficient."""
    signal = detect_explosive_move(symbol, option_type, current, history)
    if signal is None:
        return None
    result = asdict(signal)
    result["thresholds_hit"] = [
        threshold
        for threshold in SURGE_THRESHOLDS_PCT
        if signal.move_5m_pct >= threshold
    ]
    result["surge"] = bool(result["thresholds_hit"])
    result["observational_only"] = True
    return result


def detect_options_surge(
    symbol: str,
    option_type: str,
    current: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Compatibility alias used by older callers."""
    return detect_surge(symbol, option_type, current, history)


def scan_option_surge(
    symbol: str,
    chain: list[dict[str, Any]],
    history_by_instrument: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Scan a supplied option chain without performing any broker requests."""
    history_by_instrument = history_by_instrument or {}
    results: list[dict[str, Any]] = []
    for row in chain or []:
        for option_type in ("CE", "PE"):
            market = row.get("call_options" if option_type == "CE" else "put_options") or {}
            instrument_key = str(market.get("instrument_key") or "")
            if not instrument_key:
                continue
            signal = detect_surge(
                symbol,
                option_type,
                market,
                history_by_instrument.get(instrument_key, []),
            )
            if signal:
                signal.update({
                    "expiry": row.get("expiry"),
                    "strike": row.get("strike_price"),
                    "instrument_key": instrument_key,
                })
                results.append(signal)
    return sorted(results, key=lambda item: float(item.get("score", 0)), reverse=True)


__all__ = [
    "ExplosiveMoveSignal",
    "SURGE_THRESHOLDS_PCT",
    "detect_surge",
    "detect_options_surge",
    "scan_option_surge",
]
