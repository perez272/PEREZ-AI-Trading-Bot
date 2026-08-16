from typing import Any, Dict, Iterable, List

from src.options_trade_gate import (
    OptionEvidence,
    validate_trade,
    rank_candidates,
)

# Shared read-only broker client.
# LIVE ORDERS: DISABLED.
_live_option_client = None


def _get_live_option_client():
    global _live_option_client

    if _live_option_client is not None:
        return _live_option_client

    from src.broker.session_manager import SessionManager
    from src.broker.angel_client import AngelClient
    from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET

    session = SessionManager(
        API_KEY,
        CLIENT_ID,
        PASSWORD,
        TOTP_SECRET,
    )

    _live_option_client = AngelClient(session.get_client())
    return _live_option_client


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



def enrich_with_live_option_data(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read-only enrichment using Angel One FULL market data.

    Adds real:
      - LTP
      - volume
      - open interest
      - bid/ask spread
      - buy/sell quantity
      - last trade quantity

    LIVE ORDERS: DISABLED
    """
    result = dict(candidate)

    # Never trust pre-existing option evidence when live data is unavailable.
    for key in (
        "ltp",
        "volume",
        "open_interest",
        "best_bid",
        "best_ask",
        "spread_pct",
        "buy_quantity",
        "sell_quantity",
        "last_trade_qty",
        "avg_price",
        "net_change",
        "percent_change",
        "volume_score",
        "oi_score",
        "oi_change_score",
        "iv_score",
        "liquidity_score",
    ):
        result.pop(key, None)

    result["live_market_data"] = False
    result["live_data_error"] = "NOT_ATTEMPTED"

    exchange = _text(
        candidate.get("exchange")
        or candidate.get("exch_seg")
        or candidate.get("exchange_segment"),
        "NFO",
    )
    token = _text(
        candidate.get("token")
        or candidate.get("symbolToken")
        or candidate.get("symbol_token")
        or candidate.get("contract_token")
    )

    # Some callers provide the selected contract as a nested object.
    contract = candidate.get("contract")
    if isinstance(contract, dict):
        exchange = exchange or _text(
            contract.get("exchange")
            or contract.get("exch_seg"),
            "NFO",
        )
        token = token or _text(
            contract.get("token")
            or contract.get("symbolToken")
            or contract.get("symbol_token")
        )

    if not token:
        result["live_data_error"] = "MISSING_OPTION_TOKEN"
        return result

    try:
        client = _get_live_option_client()

        response = client.get_market_data(
            "FULL",
            {exchange: [token]},
        )

        fetched = (
            response.get("data", {}).get("fetched", [])
            if response and response.get("status")
            else []
        )

        if not fetched:
            result["live_data_error"] = "NO_MARKET_DATA"
            result["live_market_data"] = False
            return result

        quote = fetched[0]

        result["ltp"] = _num(quote.get("ltp"))
        result["volume"] = _num(quote.get("tradeVolume"))
        result["open_interest"] = _num(quote.get("opnInterest"))
        result["buy_quantity"] = _num(quote.get("totBuyQuan"))
        result["sell_quantity"] = _num(quote.get("totSellQuan"))
        result["last_trade_qty"] = _num(quote.get("lastTradeQty"))
        result["avg_price"] = _num(quote.get("avgPrice"))
        result["net_change"] = _num(quote.get("netChange"))
        result["percent_change"] = _num(quote.get("percentChange"))

        depth = quote.get("depth") or {}
        buys = depth.get("buy") or []
        sells = depth.get("sell") or []

        best_bid = _num(buys[0].get("price")) if buys else 0
        best_ask = _num(sells[0].get("price")) if sells else 0

        result["best_bid"] = best_bid
        result["best_ask"] = best_ask

        ltp = result["ltp"]

        if ltp > 0 and best_bid > 0 and best_ask > 0:
            result["spread_pct"] = (
                (best_ask - best_bid) / ltp
            ) * 100

        # Conservative liquidity evidence.
        if result["volume"] > 0:
            result["volume_score"] = min(
                8.0,
                max(0.0, result["volume"] / 100000.0),
            )

        if result["open_interest"] > 0:
            result["oi_score"] = 5.0

        # Greeks / IV are intentionally unavailable until a
        # reliable low-rate source is established.
        # Never fabricate IV or Greek-derived evidence.
        result["iv_score"] = 0.0
        result["iv_available"] = False
        result["greeks_available"] = False

        # OI / volume is participation evidence only.
        #
        # IMPORTANT:
        # OI / volume is NOT OI CHANGE.
        # Do not award oi_change_score from this ratio.
        #
        # Actual OI-change evidence must come from a genuine
        # previous-OI/current-OI comparison or another trusted
        # Angel One source. Until then it remains zero.
        result["oi_change_score"] = 0.0
        result["oi_change_available"] = False

        if result["volume"] > 0 and result["open_interest"] > 0:
            result["oi_volume_ratio"] = (
                result["open_interest"] / result["volume"]
            )

        if result["buy_quantity"] > result["sell_quantity"]:
            result["liquidity_score"] = min(
                7.0,
                4.0 + (
                    result["buy_quantity"]
                    / max(result["sell_quantity"], 1)
                    - 1.0
                ),
            )
        else:
            result["liquidity_score"] = 2.0

        result["live_market_data"] = True
        result["live_data_error"] = ""

    except Exception as exc:
        result["live_market_data"] = False
        result["live_data_error"] = repr(exc)

    return result


def evaluate_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate one existing scanner candidate.

    The returned object retains the original candidate and appends
    the new gate result. No broker/order method is called here.
    """

    enriched = enrich_with_live_option_data(candidate)

    # HARD FAIL-CLOSED RULE:
    # Never evaluate the options gate using stale/placeholder market data.
    if not enriched.get("live_market_data"):
        enriched["options_gate"] = {
            "score": 0,
            "eligible": False,
            "decision": "NO TRADE",
            "reasons": ["LIVE_OPTION_DATA_UNAVAILABLE"],
            "levels": {},
            "live_orders": False,
            "paper_trade": True,
        }
        enriched["options_score"] = 0
        enriched["paper_trade_candidate"] = False
        enriched["live_orders"] = False
        return enriched

    evidence = evidence_from_candidate(enriched)

    # Require real broker market data for the live-data gate.
    if not enriched.get("live_market_data"):
        enriched["options_gate"] = {
            "score": 0,
            "eligible": False,
            "decision": "NO TRADE",
            "reasons": ["LIVE_OPTION_DATA_UNAVAILABLE"],
            "levels": {},
            "live_orders": False,
            "paper_trade": True,
        }
        enriched["options_score"] = 0
        enriched["paper_trade_candidate"] = False
        enriched["live_orders"] = False
        return enriched

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


def evaluate_option_candidate(candidate):
    """Backward-compatible public entry point for main.py."""
    return evaluate_candidate(candidate)
