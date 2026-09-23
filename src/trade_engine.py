import os
from src.affordable_options import find_affordable_contract
from src.live_option_price import get_option_ltp, get_option_ltp_batch
from src.alternative_market_data import get_upstox_client
from src.active_position_guard import claim_contract
from src.upgrade_config import OPTION_MAX_PREMIUM
from src.dynamic_strike_selector import select_target_strike
from src.spread_checker import check_upstox_spread
from src.paper_trade_lifecycle import now_utc, record_event
from src.micro_account_controls import (
    MAX_ENTRY_CAPITAL_INR,
    MAX_RISK_PER_TRADE_INR,
    build_strike_sequence,
    calculate_rupee_stop_loss,
)
import logging

LOGGER = logging.getLogger(__name__)

STOP_LOSS_PCT = 0.02
TARGET1_PCT = 0.05
TARGET2_PCT = 0.10
MAX_CAPITAL_UTILIZATION = 0.90


def resolve_option_contract(symbol, spot, signal):
    """Resolve an affordable, live-priced option with provider failover."""
    if signal not in ("BUY CE", "BUY PE"):
        return {"status": "NO TRADE", "reason": "No valid CE/PE signal"}
    option_type = "CE" if signal == "BUY CE" else "PE"
    provider = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower() or "auto"
    upstox = get_upstox_client()
    target_strike = None
    if provider == "upstox" or (provider == "auto" and upstox.available()):
        try:
            target_strike = select_target_strike(symbol, float(spot), option_type, itm_depth=1)
        except ValueError:
            target_strike = None
        fallback = None
        # Micro-account selection: start ATM/1-strike ITM, then move OTM,
        # stopping after three OTM strikes and Rs 4,800 deployable capital.
        try:
            strike_sequence = build_strike_sequence(symbol, float(spot), option_type, itm_depth=1)
        except ValueError:
            strike_sequence = [target_strike] if target_strike is not None else []
        for candidate_strike in strike_sequence:
            candidate = upstox.resolve_affordable_option(
                symbol, float(spot), option_type, OPTION_MAX_PREMIUM,
                preferred_strike=candidate_strike,
            )
            if not candidate or candidate.get("status") != "CONTRACT VALID":
                continue
            try:
                required_capital = float(candidate.get("ltp", 0) or 0) * int(candidate.get("lotsize", 0) or 0)
            except (TypeError, ValueError):
                required_capital = float("inf")
            if required_capital <= MAX_ENTRY_CAPITAL_INR:
                fallback = candidate
                break
        if fallback and fallback.get("status") == "CONTRACT VALID":
            if not check_upstox_spread(
                upstox, str(fallback.get("token", "")), max_spread_pct=1.0
            ):
                LOGGER.warning(
                    "SPREAD_TOO_WIDE symbol=%s contract=%s",
                    symbol, fallback.get("contract", ""),
                )
                return {"status": "NO TRADE", "reason": "SPREAD_TOO_WIDE", "data_source": "upstox_option_chain"}
            fallback["max_premium"] = OPTION_MAX_PREMIUM
            fallback["target_strike"] = target_strike
            fallback["affordability_score"] = fallback.get("affordability_score", 0)
            fallback["required_capital"] = round(
                float(fallback.get("ltp", 0) or 0) * int(fallback.get("lotsize", 0) or 0), 2
            )
            print(f'[TRADE ENGINE] Upstox provider selected {fallback.get("contract", "UNKNOWN")} LTP=Rs {float(fallback.get("ltp", 0) or 0):.2f}')
            return fallback
        LOGGER.warning(
            "INSUFFICIENT_CAPITAL_FOR_SETUP symbol=%s option_type=%s max_entry_capital=%.2f",
            symbol, option_type, MAX_ENTRY_CAPITAL_INR,
        )
        if provider == "upstox":
            return {"status": "NO TRADE", "reason": "INSUFFICIENT_CAPITAL_FOR_SETUP", "data_source": "upstox_option_chain"}
            return {"status": "NO AFFORDABLE OPTION", "reason": "Upstox could not resolve a valid affordable option"}
    affordable = find_affordable_contract(
        symbol, spot, option_type, get_option_ltp, OPTION_MAX_PREMIUM, batch_ltp_getter=get_option_ltp_batch
    )
    if affordable.get("status") not in ("NO CONTRACT", "NO AFFORDABLE OPTION"):
        result = {
            "status": "CONTRACT VALID", "option_type": option_type, "contract": affordable["symbol"],
            "exchange": affordable["exchange"], "token": affordable["token"], "expiry": affordable["expiry"],
            "strike": affordable["strike"], "lotsize": int(affordable["lotsize"]), "ltp": float(affordable["ltp"]),
            "affordability_score": affordable["affordability_score"], "max_premium": OPTION_MAX_PREMIUM,
            "data_source": "angel_one_option_chain",
        }
        try:
            from src.live_option_price import get_option_quote
            full_quote = get_option_quote(affordable["exchange"], affordable["symbol"], affordable["token"])
            if isinstance(full_quote, dict) and float(full_quote.get("ltp", 0) or 0) > 0:
                result["live_option_quote"] = full_quote
                result["ltp"] = float(full_quote["ltp"])
        except Exception as exc:
            print(f"[TRADE ENGINE] Angel full option quote enrichment failed: {exc}")
        return result
    return affordable


def create_trade(symbol, spot, signal, capital, resolved_contract=None, learning_candidate=None, strategy=None):
    """Create a PAPER trade from one validated option contract."""
    if capital is None or float(capital) <= 0:
        return {"status": "NO CAPITAL", "reason": "No valid live available capital"}
    resolved = resolve_option_contract(symbol, spot, signal) if resolved_contract is None else dict(resolved_contract)
    if resolved.get("status") != "CONTRACT VALID":
        return resolved
    expected_option_type = "CE" if signal == "BUY CE" else "PE" if signal == "BUY PE" else None
    if expected_option_type is None or resolved.get("option_type") != expected_option_type:
        return {"status": "INVALID CONTRACT", "reason": "Validated contract does not match trade signal"}
    required = ("contract", "exchange", "token", "expiry", "strike", "lotsize", "ltp")
    missing = [key for key in required if resolved.get(key) in (None, "")]
    if missing:
        return {"status": "INVALID CONTRACT", "reason": f"Missing validated contract fields: {', '.join(missing)}"}
    lot_size = int(resolved["lotsize"])
    ltp = float(resolved["ltp"])
    if lot_size < 1 or ltp <= 0:
        return {"status": "INVALID CONTRACT", "reason": "Invalid lot size or LTP"}
    required_capital = round(ltp * lot_size, 2)
    if required_capital > MAX_ENTRY_CAPITAL_INR:
        LOGGER.warning(
            "INSUFFICIENT_CAPITAL_FOR_SETUP symbol=%s contract=%s required_capital=%.2f max_entry_capital=%.2f",
            symbol, resolved.get("contract", ""), required_capital, MAX_ENTRY_CAPITAL_INR,
        )
        return {"status": "NO TRADE", "reason": "INSUFFICIENT_CAPITAL_FOR_SETUP"}
    if ltp > OPTION_MAX_PREMIUM:
        return {"status": "PRICE_CHANGED", "reason": f"Option premium Rs {ltp:.2f} exceeds cap Rs {OPTION_MAX_PREMIUM:.2f}"}
    deployable_capital = min(float(capital), MAX_ENTRY_CAPITAL_INR)
    # Micro-account mode is strictly one-lot option buying.
    lots = 1
    quantity = lots * lot_size
    investment = round(quantity * ltp, 2)
    entry = float(ltp)
    rupee_risk = calculate_rupee_stop_loss(entry, lot_size, MAX_RISK_PER_TRADE_INR)
    stop_loss = rupee_risk["stop_loss"]
    target1 = round(entry * (1 + TARGET1_PCT), 2)
    target2 = round(entry * (1 + TARGET2_PCT), 2)
    trade = {
        "symbol": symbol, "signal": signal, "contract": resolved["contract"], "exchange": resolved["exchange"],
        "token": resolved["token"], "expiry": resolved["expiry"], "strike": resolved["strike"], "entry": entry,
        "quantity": quantity, "original_quantity": quantity, "remaining_quantity": quantity, "lots": lots,
        "investment": investment, "required_capital": required_capital,
        "capital_available": round(min(float(capital), 5000.0), 2),
        "capital_utilization_pct": round(investment / float(capital) * 100.0, 2), "initial_stop_loss": stop_loss,
        "stop_loss": stop_loss, "target1": target1, "target2": target2, "target": target2, "partial_booked": False,
        "realized_pnl": 0.0, "status": "PAPER TRADE ACTIVE", "live_orders": False,
        "data_source": resolved.get("data_source", "unknown"),
        "strategy": strategy or "CORE",
        "detected_at": "", "opened_at": "", "target1_at": "", "closed_at": "",
    }
    if learning_candidate:
        trade["learning_candidate"] = dict(learning_candidate)
        trade["detected_at"] = str(
            learning_candidate.get("detection_ts")
            or learning_candidate.get("detected_at")
            or learning_candidate.get("observed_ts")
            or learning_candidate.get("ts")
            or ""
        )
    if os.getenv("PAPER_MODE", "false").strip().lower() != "true":
        return {"status": "NO TRADE", "reason": "PAPER_MODE is not enabled"}
    if os.getenv("ORDERS_ENABLED", "false").strip().lower() != "false":
        return {"status": "NO TRADE", "reason": "ORDERS_ENABLED is not false"}
    import uuid
    trade["trade_id"] = str(uuid.uuid4())
    claimed, reason = claim_contract(trade["contract"], trade["symbol"], trade["trade_id"])
    if not claimed:
        return {"status": "NO TRADE", "reason": f"ACTIVE POSITION GUARD: {reason}"}
    trade["opened_at"] = now_utc()
    record_event(
        trade, "OPEN", ts=trade["opened_at"], entry=entry, quantity=quantity,
        investment=investment, stop_loss=stop_loss, target1=target1, target2=target2,
        detected_at=trade.get("detected_at") or None,
    )
    return trade
