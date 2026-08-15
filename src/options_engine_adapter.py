from typing import Any, Dict, Iterable, List

from src.options_trade_gate import (
    OptionEvidence,
    validate_trade,
    rank_candidates,
)


# ============================================================
# PEREZ AI — OPTIONS ENGINE ADAPTER
# ============================================================
# This layer sits BETWEEN the existing options ranking engine
# and paper-trade execution.
#
# Existing scanner/ranking is preserved.
# This adapter adds the stricter evidence/risk gate.
#
# LIVE ORDERS: DISABLED
# ============================================================


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def evidence_from_candidate(candidate: Dict[str, Any]) -> OptionEvidence:
    """
    Convert the existing scanner's candidate dictionary into the
    common options evidence model.

    Multiple aliases are accepted so the adapter can work with
    existing scanner field names without changing the scanner.
    """

    return OptionEvidence(
        symbol=_text(
            candidate.get("symbol")
            or candidate.get("underlying")
            or candidate.get("name")
        ),
        option_type=_text(
            candidate.get("option_type")
            or candidate.get("type")
            or candidate.get("right")
        ).upper(),
        expiry=_text(
            candidate.get("expiry")
            or candidate.get("expiry_date")
        ),
        ltp=_num(
            candidate.get("ltp")
            or candidate.get("option_ltp")
            or candidate.get("close")
        ),

        trend_score=_num(
            candidate.get("trend_score")
            or candidate.get("trend")
        ),
        momentum_score=_num(
            candidate.get("momentum_score")
            or candidate.get("momentum")
        ),
        volume_score=_num(
            candidate.get("volume_score")
            or candidate.get("volume")
        ),
        vwap_score=_num(
            candidate.get("vwap_score")
            or candidate.get("vwap")
        ),
        volatility_score=_num(
            candidate.get("volatility_score")
            or candidate.get("volatility")
        ),
        structure_score=_num(
            candidate.get("structure_score")
            or candidate.get("structure")
        ),

        oi_score=_num(
            candidate.get("oi_score")
            or candidate.get("open_interest_score")
        ),
        oi_change_score=_num(
            candidate.get("oi_change_score")
            or candidate.get("oi_change")
            or candidate.get("oi_change_pct")
        ),
        iv_score=_num(
            candidate.get("iv_score")
            or candidate.get("implied_volatility_score")
        ),
        liquidity_score=_num(
            candidate.get("liquidity_score")
            or candidate.get("liquidity")
        ),

        index_confirmation=_num(
            candidate.get("index_confirmation")
            or candidate.get("index_score")
        ),
        news_confirmation=_num(
            candidate.get("news_confirmation")
            or candidate.get("news_score")
        ),
        event_risk_penalty=_num(
            candidate.get("event_risk_penalty")
            or candidate.get("event_penalty")
        ),

        spread_pct=_num(
            candidate.get("spread_pct")
            or candidate.get("spread")
        ),
        slippage_pct=_num(
            candidate.get("slippage_pct")
            or candidate.get("slippage")
        ),
    )


def evaluate_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate one existing scanner candidate.

    The returned object retains the original candidate and appends
    the new gate result. No broker/order method is called here.
    """

    evidence = evidence_from_candidate(candidate)
    gate = validate_trade(evidence)

    result = dict(candidate)
    result["options_gate"] = gate
    result["options_score"] = gate["score"]
    result["paper_trade_candidate"] = gate["eligible"]
    result["live_orders"] = False

    return result


def evaluate_candidates(
    candidates: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Evaluate and rank existing scanner candidates.

    Only candidates passing the strict options gate are admitted.
    """

    candidates = list(candidates)

    evidence = []
    mapping = []

    for candidate in candidates:
        try:
            e = evidence_from_candidate(candidate)
            evidence.append(e)
            mapping.append(candidate)
        except Exception:
            continue

    ranked = rank_candidates(evidence)

    output = []

    for candidate, gate in zip(mapping, ranked):
        item = dict(candidate)
        item["options_gate"] = gate
        item["options_score"] = gate["score"]
        item["paper_trade_candidate"] = gate["eligible"]
        item["live_orders"] = False
        output.append(item)

    return output


def select_paper_trade(candidates: Iterable[Dict[str, Any]]):
    """
    Return the strongest candidate that passes the strict gate.

    IMPORTANT:
    This function only selects.
    It does not place an order.
    """

    evaluated = evaluate_candidates(candidates)

    eligible = [
        x for x in evaluated
        if x.get("paper_trade_candidate") is True
    ]

    if not eligible:
        return None

    eligible.sort(
        key=lambda x: x.get("options_score", 0),
        reverse=True,
    )

    return eligible[0]


def print_gate_summary(result: Dict[str, Any]) -> None:
    gate = result.get("options_gate", {})

    print("-" * 72)
    print(
        f"{result.get('symbol', '')} "
        f"{result.get('option_type', '')}"
    )
    print(f"OPTIONS SCORE : {gate.get('score', 0)}/100")
    print(
        f"DECISION      : "
        f"{gate.get('decision', 'NO TRADE')}"
    )

    levels = gate.get("levels", {})

    if levels:
        print(f"ENTRY         : Rs {levels.get('entry')}")
        print(f"STOP LOSS     : Rs {levels.get('stop_loss')}")
        print(f"TARGET 5%     : Rs {levels.get('T1_5%')}")
        print(f"TARGET 10%    : Rs {levels.get('T2_10%')}")
        print(f"TARGET 15%    : Rs {levels.get('T3_15%')}")
        print(f"TARGET 20%    : Rs {levels.get('T4_20%')}")

    reasons = gate.get("reasons", [])

    if reasons:
        print("REJECT REASONS:", ", ".join(reasons))

    print("PAPER TRADE   :", True)
    print("LIVE ORDERS   :", False)


if __name__ == "__main__":
    print("=" * 72)
    print("PEREZ AI — OPTIONS ENGINE ADAPTER")
    print("=" * 72)
    print("Existing scanner : PRESERVED")
    print("Existing ranking : PRESERVED")
    print("New gate         : >=80")
    print("Stop loss        : 2%")
    print("Targets          : 5/10/15/20%")
    print("Paper trading    : ENABLED")
    print("Live orders      : DISABLED")
    print("=" * 72)
