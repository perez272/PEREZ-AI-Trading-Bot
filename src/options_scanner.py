"""Separate top-options scan fed by the strongest share/index candidates.

This module intentionally does NOT scan the entire NFO instrument master every
cycle. It takes a small ranked share universe, resolves a concrete CE/PE
contract, enriches it with live read-only Angel One market data, and ranks the
resulting option candidates. Paper trading only; no order placement occurs.
"""

from typing import Any, Dict, Iterable, List

from src.options_engine_adapter import evaluate_option_candidate
from src.trade_engine import resolve_option_contract


def _option_type(signal: str) -> str:
    return "CE" if str(signal).upper() == "BUY CE" else "PE"


def scan_top_options(share_results: Iterable[Dict[str, Any]], max_underlyings: int = 10) -> List[Dict[str, Any]]:
    """Resolve and rank options separately from the underlying-share scan."""
    candidates = []
    ranked_shares = sorted(
        [x for x in share_results if x.get("status") == "OK"],
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    for share in ranked_shares[:max_underlyings]:
        signal = str(share.get("signal", "")).upper()
        if signal not in {"BUY CE", "BUY PE"}:
            continue

        symbol = str(share.get("symbol", "")).upper()
        contract = resolve_option_contract(symbol, float(share.get("close", 0)), signal)
        if contract.get("status") != "CONTRACT VALID":
            print(f"OPTION {symbol:<14} status=CONTRACT_REJECTED reason={contract.get('status', 'UNKNOWN')}")
            continue

        item = {
            "symbol": symbol,
            "option_type": _option_type(signal),
            "expiry": contract.get("expiry", ""),
            "exchange": contract.get("exchange", "NFO"),
            "token": contract.get("token", ""),
            "underlying_score": share.get("score", 0),
            "underlying_close": share.get("close", 0),
            "underlying_rsi": share.get("rsi", 0),
            "underlying_trend": share.get("trend", ""),
            "ltp": contract.get("ltp", 0),
            "trend_score": share.get("score", 0),
            "momentum_score": share.get("score", 0),
            "volume_score": share.get("volume_ratio", 0),
            "vwap_score": share.get("score", 0),
            "index_confirmation": 8 if share.get("trend") else 0,
            "oi_score": 0,
            "oi_change_score": 0,
            "iv_score": 0,
            "liquidity_score": 0,
            "volatility_score": 0,
            "structure_score": 0,
            "news_confirmation": 0,
            "event_risk_penalty": 0,
            "spread_pct": 0,
            "slippage_pct": 0,
        }
        evaluated = evaluate_option_candidate(item)
        gate = evaluated.get("options_gate", {})
        evaluated["options_score"] = evaluated.get("options_score", gate.get("score", 0))
        candidates.append(evaluated)

    candidates.sort(
        key=lambda x: (x.get("paper_trade_candidate", False), x.get("options_score", 0), x.get("underlying_score", 0)),
        reverse=True,
    )

    print("\nTOP OPTIONS")
    print("-" * 110)
    if not candidates:
        print("No option contracts passed contract resolution from the current top-share signals.")
    for item in candidates[:10]:
        gate = item.get("options_gate", {})
        print(
            f"OPTION {item.get('symbol',''):<14} {item.get('option_type',''):<2} "
            f"expiry={item.get('expiry','')} ltp={item.get('ltp', 0):.2f} "
            f"share_score={item.get('underlying_score', 0):>3} "
            f"option_score={item.get('options_score', 0):>3} "
            f"decision={gate.get('decision', 'NO TRADE')} "
            f"paper={item.get('paper_trade_candidate', False)}"
        )
    print("-" * 110)
    return candidates


def select_best_option(options: Iterable[Dict[str, Any]]):
    eligible = [x for x in options if x.get("paper_trade_candidate") is True]
    if not eligible:
        return None
    return max(eligible, key=lambda x: x.get("options_score", 0))
