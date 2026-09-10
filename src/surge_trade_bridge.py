from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.alternative_market_data import get_upstox_client
from src.surge_trade_gate import SurgeEvidence, validate_surge
from src.trade_engine import create_trade
from src.upgrade_config import OPTION_MAX_PREMIUM


MAX_EVENT_AGE_SECONDS = 60.0
TIER1_DB = Path(os.getenv("TIER1_OPTION_MEMORY", "data/memory/tier1_option_moves.sqlite3"))
CLAIM_TABLE = "surge_bridge_claims"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _quote_value(quote: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = _num(quote.get(key))
        if value > 0:
            return value
    return 0.0


def _book_prices(quote: dict[str, Any]) -> tuple[float, float]:
    depth = quote.get("depth") or {}
    buys = depth.get("buy") or []
    sells = depth.get("sell") or []

    bid = _num(buys[0].get("price")) if buys and isinstance(buys[0], dict) else 0.0
    ask = _num(sells[0].get("price")) if sells and isinstance(sells[0], dict) else 0.0

    bid = bid or _num(quote.get("bid_price"))
    ask = ask or _num(quote.get("ask_price"))
    return bid, ask


def _event_age(event: dict[str, Any]) -> float:
    raw = event.get("detection_ts") or event.get("observed_ts")
    if not raw:
        return 999999.0
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except (TypeError, ValueError):
        return 999999.0


def _features(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("features")
    if isinstance(value, dict):
        return value
    raw = event.get("features_json")
    if raw:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {}


def _claim_event(event_id: int) -> bool:
    """Atomically claim an event so main.py and the bridge worker cannot duplicate it."""
    TIER1_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(TIER1_DB, timeout=5) as db:
        db.execute(
            f"CREATE TABLE IF NOT EXISTS {CLAIM_TABLE} (event_id INTEGER PRIMARY KEY, claimed_at TEXT NOT NULL)"
        )
        cur = db.execute(
            f"INSERT OR IGNORE INTO {CLAIM_TABLE}(event_id, claimed_at) VALUES (?, ?)",
            (int(event_id), datetime.now(timezone.utc).isoformat()),
        )
        return cur.rowcount == 1


def _release_event(event_id: int) -> None:
    try:
        with sqlite3.connect(TIER1_DB, timeout=5) as db:
            db.execute(f"DELETE FROM {CLAIM_TABLE} WHERE event_id=?", (int(event_id),))
    except Exception:
        pass


def evaluate_pending_surge(event: dict[str, Any]) -> dict[str, Any]:
    """Validate one persisted early event against a fresh Upstox quote."""
    symbol = str(event.get("symbol") or "").upper().strip()
    option_type = str(event.get("option_type") or "").upper().strip()
    instrument_key = str(event.get("instrument_key") or "").strip()
    expiry = str(event.get("expiry") or "").strip()
    strike = _num(event.get("strike"))
    features = _features(event)

    if _event_age(event) > MAX_EVENT_AGE_SECONDS:
        return {"eligible": False, "terminal": True, "reason": "STALE_EARLY_EVENT", "reasons": ["STALE_EARLY_EVENT"]}

    client = get_upstox_client()
    if not client.available():
        return {"eligible": False, "terminal": False, "reason": "UPSTOX_UNAVAILABLE", "reasons": ["UPSTOX_UNAVAILABLE"]}

    contract = client.resolve_option_by_instrument_key(symbol, instrument_key, expiry=expiry or None)
    if not contract:
        return {"eligible": False, "terminal": False, "reason": "EXACT_CONTRACT_UNRESOLVED", "reasons": ["EXACT_CONTRACT_UNRESOLVED"]}

    quote = client.get_full_quote(instrument_key)
    if not quote:
        return {"eligible": False, "terminal": False, "reason": "FRESH_OPTION_QUOTE_UNAVAILABLE", "reasons": ["FRESH_OPTION_QUOTE_UNAVAILABLE"]}

    ltp = _quote_value(quote, "last_price", "last_traded_price", "ltp")
    volume = _quote_value(quote, "volume", "tradeVolume")
    oi = _quote_value(quote, "oi", "opnInterest")
    iv = _num(features.get("iv"))
    bid, ask = _book_prices(quote)

    spread_pct = ((ask - bid) / ltp * 100.0) if ltp > 0 and bid > 0 and ask >= bid else 999.0
    slippage_pct = ((ask - ltp) / ltp * 100.0) if ltp > 0 and ask > 0 else 999.0

    evidence = SurgeEvidence(
        symbol=symbol,
        option_type=option_type,
        instrument_key=instrument_key,
        expiry=expiry,
        strike=strike,
        ltp=ltp,
        bid=bid,
        ask=ask,
        volume=volume,
        oi=oi,
        iv=iv,
        move_1m_pct=_num(event.get("move_1m_pct")),
        move_3m_pct=_num(event.get("move_3m_pct")),
        move_5m_pct=_num(event.get("move_5m_pct")),
        velocity=_num(event.get("velocity")),
        acceleration=_num(event.get("acceleration")),
        volume_ratio=_num(event.get("volume_ratio")),
        spread_pct=spread_pct,
        slippage_pct=slippage_pct,
        detector_score=_num(event.get("score")),
    )

    gate = validate_surge(evidence, OPTION_MAX_PREMIUM)
    return {
        "eligible": bool(gate["eligible"]),
        "terminal": True,
        "reason": ", ".join(gate["reasons"]) or "SURGE_GATE_PASSED",
        "reasons": gate["reasons"],
        "gate": gate,
        "contract": contract,
        "quote": quote,
        "ltp": ltp,
        "evidence": evidence,
    }


def create_surge_trade(
    event: dict[str, Any],
    capital: float,
    risk_manager: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Create an exact-contract paper trade after surge + risk validation."""
    event_id = int(event.get("id"))
    if not _claim_event(event_id):
        return None, {"eligible": False, "terminal": False, "reason": "EVENT_ALREADY_CLAIMED", "reasons": ["EVENT_ALREADY_CLAIMED"]}

    result = evaluate_pending_surge(event)

    if not result.get("eligible"):
        if not result.get("terminal"):
            _release_event(event_id)
        return None, result

    symbol = str(event.get("symbol") or "").upper().strip()
    option_type = str(event.get("option_type") or "").upper().strip()
    signal = "BUY CE" if option_type == "CE" else "BUY PE"

    allowed, reason, summary = __import__(
        "src.risk_manager", fromlist=["can_open_new_trade"]
    ).can_open_new_trade(3, None, capital)

    if not allowed:
        _release_event(event_id)
        result["eligible"] = False
        result["terminal"] = False
        result["reason"] = f"RISK_BLOCK:{reason}"
        result["reasons"] = [f"RISK_BLOCK:{reason}"]
        return None, result

    contract = dict(result["contract"])
    contract["ltp"] = result["ltp"]
    contract["data_source"] = "upstox_surge_fresh_quote"

    trade = create_trade(
        symbol,
        float(event.get("strike") or 0.0),
        signal,
        capital,
        resolved_contract=contract,
    )

    if trade.get("status") != "PAPER TRADE ACTIVE":
        result["eligible"] = False
        result["terminal"] = True
        result["reason"] = trade.get("reason", trade.get("status", "CREATE_TRADE_FAILED"))
        result["reasons"] = [result["reason"]]
        return None, result

    import uuid

    trade_id = str(uuid.uuid4())
    lineage_id = trade.get("lineage_id") or trade_id
    trade["trade_id"] = trade_id
    trade["lineage_id"] = lineage_id
    trade["strategy"] = "SURGE_EARLY_EXPLOSIVE"
    trade["surge_score"] = result["gate"]["score"]
    trade["surge_reasons"] = result["gate"]["reasons"]
    trade["surge_move_1m_pct"] = result["evidence"].move_1m_pct
    trade["surge_move_3m_pct"] = result["evidence"].move_3m_pct
    trade["surge_move_5m_pct"] = result["evidence"].move_5m_pct
    trade["option_live_ltp_at_gate"] = result["ltp"]

    allowed, reason = risk_manager.can_open_trade(trade_id, lineage_id=lineage_id)
    if not allowed:
        _release_event(event_id)
        result["eligible"] = False
        result["terminal"] = False
        result["reason"] = f"RISK_MANAGER:{reason}"
        result["reasons"] = [result["reason"]]
        return None, result

    risk_manager.register_entry(trade_id, float(trade["entry"]), lineage_id=lineage_id)
    return trade, result
