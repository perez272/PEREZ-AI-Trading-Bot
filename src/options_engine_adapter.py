from typing import Any, Dict, Iterable, List

from src.options_trade_gate import OptionEvidence, validate_trade

_live_option_client = None


def _get_live_option_client():
    global _live_option_client
    if _live_option_client is not None:
        return _live_option_client
    from src.broker.session_manager import SessionManager
    from src.broker.angel_client import AngelClient
    from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
    session = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
    _live_option_client = AngelClient(session.get_client())
    return _live_option_client


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value).strip()


def evidence_from_candidate(candidate: Dict[str, Any]) -> OptionEvidence:
    return OptionEvidence(
        symbol=_text(candidate.get("symbol") or candidate.get("underlying") or candidate.get("name")),
        option_type=_text(candidate.get("option_type") or candidate.get("type") or candidate.get("right")).upper(),
        expiry=_text(candidate.get("expiry") or candidate.get("expiry_date")),
        ltp=_num(candidate.get("ltp") or candidate.get("option_ltp") or candidate.get("close")),
        trend_score=_num(candidate.get("trend_score")),
        momentum_score=_num(candidate.get("momentum_score")),
        volume_score=_num(candidate.get("volume_score")),
        vwap_score=_num(candidate.get("vwap_score")),
        volatility_score=_num(candidate.get("volatility_score")),
        structure_score=_num(candidate.get("structure_score")),
        oi_score=_num(candidate.get("oi_score")),
        oi_change_score=_num(candidate.get("oi_change_score")),
        iv_score=_num(candidate.get("iv_score")),
        liquidity_score=_num(candidate.get("liquidity_score")),
        index_confirmation=_num(candidate.get("index_confirmation")),
        news_confirmation=_num(candidate.get("news_confirmation")),
        event_risk_penalty=_num(candidate.get("event_risk_penalty")),
        spread_pct=_num(candidate.get("spread_pct")),
        slippage_pct=_num(candidate.get("slippage_pct")),
        underlying_signal=_text(candidate.get("underlying_signal")),
        mtf_direction=_text(candidate.get("mtf_direction")),
        percent_change=_num(candidate.get("percent_change")),
        avg_price=_num(candidate.get("avg_price")),
        best_bid=_num(candidate.get("best_bid")),
        best_ask=_num(candidate.get("best_ask")),
        live_market_data=bool(candidate.get("live_market_data")),
    )


def enrich_with_live_option_data(candidate: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(candidate)
    for key in (
        "ltp", "volume", "open_interest", "best_bid", "best_ask", "spread_pct", "slippage_pct",
        "buy_quantity", "sell_quantity", "last_trade_qty", "avg_price", "net_change", "percent_change",
        "volume_score", "oi_score", "oi_change_score", "iv_score", "liquidity_score",
        "trend_score", "momentum_score", "vwap_score",
    ):
        result.pop(key, None)
    result["live_market_data"] = False
    result["live_data_error"] = "NOT_ATTEMPTED"
    exchange = _text(candidate.get("exchange") or candidate.get("exch_seg") or candidate.get("exchange_segment"), "NFO")
    token = _text(candidate.get("token") or candidate.get("symbolToken") or candidate.get("symbol_token") or candidate.get("contract_token"))
    contract = candidate.get("contract")
    if isinstance(contract, dict):
        exchange = _text(contract.get("exchange") or contract.get("exch_seg"), exchange)
        token = _text(contract.get("token") or contract.get("symbolToken") or contract.get("symbol_token"), token)
    if not token:
        result["live_data_error"] = "MISSING_OPTION_TOKEN"
        return result
    try:
        response = _get_live_option_client().get_market_data("FULL", {exchange: [token]})
        fetched = response.get("data", {}).get("fetched", []) if isinstance(response, dict) and response.get("status") else []
        if not fetched:
            result["live_data_error"] = "NO_MARKET_DATA"
            return result
        quote = fetched[0]
        ltp = _num(quote.get("ltp"))
        if ltp <= 0:
            result["live_data_error"] = "INVALID_LTP"
            return result
        result.update({
            "ltp": ltp,
            "volume": _num(quote.get("tradeVolume")),
            "open_interest": _num(quote.get("opnInterest")),
            "buy_quantity": _num(quote.get("totBuyQuan")),
            "sell_quantity": _num(quote.get("totSellQuan")),
            "last_trade_qty": _num(quote.get("lastTradeQty")),
            "avg_price": _num(quote.get("avgPrice")),
            "net_change": _num(quote.get("netChange")),
            "percent_change": _num(quote.get("percentChange")),
        })
        depth = quote.get("depth") or {}
        buys, sells = depth.get("buy") or [], depth.get("sell") or []
        bid = _num(buys[0].get("price")) if buys else 0.0
        ask = _num(sells[0].get("price")) if sells else 0.0
        result["best_bid"], result["best_ask"] = bid, ask
        if bid > 0 and ask > 0 and ask >= bid:
            result["spread_pct"] = max(0.0, (ask - bid) / ltp * 100.0)
            result["slippage_pct"] = max(0.0, (ask - ltp) / ltp * 100.0)
        else:
            result["spread_pct"] = result["slippage_pct"] = 999.0

        pct = result["percent_change"]
        avg = result["avg_price"]
        result["trend_score"] = min(15.0, max(0.0, pct * 3.0))
        result["momentum_score"] = min(10.0, max(0.0, pct * 2.0))
        result["vwap_score"] = 7.0 if avg > 0 and ltp > avg else (3.0 if avg > 0 and ltp == avg else 0.0)
        result["volume_score"] = min(8.0, max(0.0, result["volume"] / 100000.0)) if result["volume"] > 0 else 0.0
        result["oi_score"] = 5.0 if result["open_interest"] > 0 else 0.0
        result["oi_change_score"] = 0.0
        result["oi_change_available"] = False
        result["iv_score"] = 0.0
        result["iv_available"] = False
        result["greeks_available"] = False
        if result["buy_quantity"] + result["sell_quantity"] > 0:
            imbalance = result["buy_quantity"] / max(result["sell_quantity"], 1.0)
            result["liquidity_score"] = min(7.0, max(0.0, 3.0 + imbalance - 1.0))
        else:
            result["liquidity_score"] = 0.0
        result["live_market_data"] = True
        result["live_data_error"] = ""
        return result
    except Exception as exc:
        result["live_data_error"] = repr(exc)
        return result


def evaluate_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    enriched = enrich_with_live_option_data(candidate)
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
    gate = validate_trade(evidence_from_candidate(enriched))
    enriched["options_gate"] = gate
    enriched["options_score"] = gate["score"]
    enriched["paper_trade_candidate"] = gate["eligible"]
    enriched["live_orders"] = False
    return enriched


def evaluate_option_candidate(candidate):
    return evaluate_candidate(candidate)


def evaluate_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [evaluate_candidate(c) for c in candidates]


def select_paper_trade(candidates: Iterable[Dict[str, Any]]):
    eligible = [x for x in evaluate_candidates(candidates) if x.get("paper_trade_candidate") is True]
    return max(eligible, key=lambda x: x.get("options_score", 0), default=None)


def print_gate_summary(result: Dict[str, Any]) -> None:
    gate = result.get("options_gate", {})
    print("-" * 72)
    print(f"{result.get('symbol', '')} {result.get('option_type', '')}")
    print(f"OPTIONS SCORE : {gate.get('score', 0)}/100")
    print(f"DECISION      : {gate.get('decision', 'NO TRADE')}")
    if gate.get("reasons"):
        print("REJECT REASONS:", ", ".join(gate["reasons"]))
    print("PAPER TRADE   :", True)
    print("LIVE ORDERS   :", False)
