import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.affordable_options import find_affordable_contract
from src.live_option_price import get_option_ltp, get_option_ltp_batch
from src.alternative_market_data import get_upstox_client
from src.active_position_guard import claim_contract
from src.upgrade_config import OPTION_MAX_PREMIUM, MAX_SPREAD_PCT, MAX_SLIPPAGE_PCT
from src.dynamic_strike_selector import select_target_strike
from src.spread_checker import is_spread_safe
from src.paper_trade_lifecycle import now_utc, record_event

STOP_LOSS_PCT = 0.02
TARGET1_PCT = 0.05
TARGET2_PCT = 0.10
MAX_DEPLOYMENT_INR = 4200.0
PLANNED_POSITION_RISK_INR = 50.0
MAX_POSITION_RISK_INR = 75.0


def _parse_option_expiry(value):
    """Parse Angel One and Upstox expiry representations without guessing."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # ISO date or datetime (Upstox commonly returns an ISO timestamp).
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in (
        "%d%b%Y", "%d-%b-%Y", "%d%b%y", "%d-%b-%y",
        "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d", "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(raw.upper(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_option_quote_timestamp(value):
    """Return quote timestamp in UTC; naive exchange feed times mean IST."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdigit():
            stamp = float(value)
            if stamp > 1e12:  # milliseconds since epoch
                stamp /= 1000.0
            parsed = datetime.fromtimestamp(stamp, tz=timezone.utc)
        else:
            raw = str(value).strip()
            parsed = None
            for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except (TypeError, ValueError, OverflowError, OSError):
        return None


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
        fallback = upstox.resolve_affordable_option(
            symbol, float(spot), option_type, float("inf"), preferred_strike=target_strike
        )
        if fallback and fallback.get("status") == "CONTRACT VALID":
            fresh_quote = upstox.get_full_quote(str(fallback.get("token", "")))
            if not is_spread_safe(fresh_quote, max_spread_pct=MAX_SPREAD_PCT):
                return {"status": "NO TRADE", "reason": "TRADE_BLOCKED_SPREAD", "data_source": "upstox_option_chain"}
            if not isinstance(fresh_quote, dict):
                return {"status": "NO TRADE", "reason": "FRESH_OPTION_QUOTE_UNAVAILABLE", "data_source": "upstox_option_chain"}
            fresh_ltp = fresh_quote.get("last_price", fresh_quote.get("ltp", fresh_quote.get("last_traded_price", 0)))
            try:
                fresh_ltp = float(fresh_ltp or 0)
            except (TypeError, ValueError):
                fresh_ltp = 0.0
            if fresh_ltp <= 0:
                return {"status": "NO TRADE", "reason": "INVALID_FRESH_OPTION_LTP", "data_source": "upstox_option_chain"}
            fallback["ltp"] = fresh_ltp
            fallback["live_option_quote"] = fresh_quote
            fallback["target_strike"] = target_strike
            fallback["affordability_score"] = fallback.get("affordability_score", 0)
            print(f'[TRADE ENGINE] Upstox provider selected {fallback.get("contract", "UNKNOWN")} LTP=Rs {float(fallback.get("ltp", 0) or 0):.2f}')
            return fallback
        if provider == "upstox":
            return {"status": "NO AFFORDABLE OPTION", "reason": "Upstox could not resolve a valid affordable option"}
    affordable = find_affordable_contract(
        symbol, spot, option_type, get_option_ltp, float("inf"), batch_ltp_getter=get_option_ltp_batch
    )
    if affordable.get("status") not in ("NO CONTRACT", "NO AFFORDABLE OPTION"):
        result = {
            "status": "CONTRACT VALID", "option_type": option_type, "contract": affordable["symbol"],
            "exchange": affordable["exchange"], "token": affordable["token"], "expiry": affordable["expiry"],
            "strike": affordable["strike"], "lotsize": int(affordable["lotsize"]), "ltp": float(affordable["ltp"]),
            "affordability_score": affordable["affordability_score"],
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


def create_trade(symbol, spot, signal, capital, resolved_contract=None, learning_candidate=None, strategy=None, trade_id=None, defer_open_event=False):
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
    expiry_date = _parse_option_expiry(resolved.get("expiry"))
    if expiry_date is None or expiry_date < datetime.now(ZoneInfo("Asia/Kolkata")).date():
        return {"status": "INVALID CONTRACT", "reason": "INVALID_OR_EXPIRED_OPTION_EXPIRY"}
    lot_size = int(resolved["lotsize"])
    ltp = float(resolved["ltp"])
    if lot_size < 1 or ltp <= 0:
        return {"status": "INVALID CONTRACT", "reason": "Invalid lot size or LTP"}

    # Use the executable ask, never LTP, as the simulated long-option fill.
    quote = resolved.get("live_option_quote")
    quote = quote if isinstance(quote, dict) else {}
    depth = quote.get("depth") or {}
    if not isinstance(depth, dict):
        return {"status": "NO TRADE", "reason": "OPTION_BOOK_DEPTH_INVALID"}
    buys = depth.get("buy") or []
    sells = depth.get("sell") or []
    try:
        bid = float((buys[0] or {}).get("price", 0) or quote.get("bid_price", 0) or 0) if buys or quote.get("bid_price") else 0.0
        ask = float((sells[0] or {}).get("price", 0) or quote.get("ask_price", 0) or 0) if sells or quote.get("ask_price") else 0.0
    except (TypeError, ValueError, IndexError, AttributeError):
        return {"status": "NO TRADE", "reason": "OPTION_BOOK_PRICE_INVALID"}
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask <= 0 or ask < bid:
        return {"status": "NO TRADE", "reason": "FRESH_EXECUTABLE_BID_ASK_REQUIRED"}
    # Provider timestamp is mandatory. Missing, malformed, future, or >5s-old
    # quotes fail closed; underlying candle freshness is checked separately.
    raw_ts = next((quote.get(k) for k in (
        "timestamp", "last_trade_time", "last_traded_time", "ltt",
        "exchFeedTime", "exchTradeTime", "exchange_timestamp", "feed_time",
    ) if quote.get(k) not in (None, "")), None)
    quote_time = _parse_option_quote_timestamp(raw_ts)
    if quote_time is None:
        return {"status": "NO TRADE", "reason": "OPTION_QUOTE_TIMESTAMP_MISSING_OR_INVALID"}
    quote_age = (datetime.now(timezone.utc) - quote_time).total_seconds()
    if quote_age < 0 or quote_age > 5.0:
        return {"status": "NO TRADE", "reason": f"OPTION_QUOTE_STALE_OR_FUTURE ({quote_age:.2f}s)"}
    # A valid top-of-book price without displayed size is not executable evidence.
    try:
        bid_qty = float((buys[0] or {}).get("quantity", (buys[0] or {}).get("qty", 0)) or quote.get("total_buy_quantity", quote.get("totBuyQuan", 0)) or 0) if buys else float(quote.get("total_buy_quantity", quote.get("totBuyQuan", 0)) or 0)
        ask_qty = float((sells[0] or {}).get("quantity", (sells[0] or {}).get("qty", 0)) or quote.get("total_sell_quantity", quote.get("totSellQuan", 0)) or 0) if sells else float(quote.get("total_sell_quantity", quote.get("totSellQuan", 0)) or 0)
    except (TypeError, ValueError, IndexError):
        return {"status": "NO TRADE", "reason": "OPTION_BOOK_DEPTH_INVALID"}
    if not math.isfinite(bid_qty) or not math.isfinite(ask_qty) or bid_qty <= 0 or ask_qty <= 0:
        return {"status": "NO TRADE", "reason": "OPTION_BOOK_DEPTH_UNAVAILABLE"}
    if not all(math.isfinite(value) and value > 0 for value in (bid, ask, ltp)):
        return {"status": "NO TRADE", "reason": "OPTION_BOOK_PRICE_INVALID"}
    spread_pct = (ask - bid) / bid * 100.0
    if spread_pct > MAX_SPREAD_PCT:
        return {"status": "NO TRADE", "reason": f"TRADE_BLOCKED_SPREAD ({spread_pct:.3f}% > {MAX_SPREAD_PCT:.2f}%)"}
    slippage_pct = max(0.0, (ask - ltp) / ltp * 100.0)
    if slippage_pct > MAX_SLIPPAGE_PCT:
        return {"status": "NO TRADE", "reason": f"HIGH_ENTRY_SLIPPAGE ({slippage_pct:.3f}% > {MAX_SLIPPAGE_PCT:.2f}%)"}
    entry = ask
    deployable_capital = min(float(capital), MAX_DEPLOYMENT_INR)
    per_lot_investment = entry * lot_size
    per_lot_risk = entry * STOP_LOSS_PCT * lot_size
    if per_lot_investment <= 0 or per_lot_risk <= 0:
        return {"status": "INVALID CONTRACT", "reason": "Invalid executable entry/risk"}
    lots_by_capital = int(deployable_capital // per_lot_investment)
    lots_by_planned_risk = int(PLANNED_POSITION_RISK_INR // per_lot_risk)
    lots_by_absolute_risk = int(MAX_POSITION_RISK_INR // per_lot_risk)
    lots = min(lots_by_capital, lots_by_planned_risk, lots_by_absolute_risk)
    if lots < 1:
        if per_lot_risk > MAX_POSITION_RISK_INR:
            return {"status": "RISK_TOO_HIGH", "reason": f"One lot risk Rs {per_lot_risk:.2f} exceeds absolute Rs {MAX_POSITION_RISK_INR:.2f}"}
        return {"status": "LOW CAPITAL", "reason": f"One lot needs Rs {per_lot_investment:.2f}; deployment ceiling Rs {deployable_capital:.2f}"}
    quantity = lots * lot_size
    investment = round(quantity * entry, 2)
    total_risk = round(entry * STOP_LOSS_PCT * quantity, 2)
    if total_risk > MAX_POSITION_RISK_INR:
        return {"status": "RISK_TOO_HIGH", "reason": f"Position risk Rs {total_risk:.2f} exceeds absolute limit"}
    stop_loss = round(entry * (1 - STOP_LOSS_PCT), 2)
    target1 = round(entry * (1 + TARGET1_PCT), 2)
    target2 = round(entry * (1 + TARGET2_PCT), 2)
    trade = {
        "symbol": symbol, "signal": signal, "contract": resolved["contract"], "exchange": resolved["exchange"],
        "token": resolved["token"], "expiry": resolved["expiry"], "strike": resolved["strike"], "entry": entry,
        "quantity": quantity, "original_quantity": quantity, "remaining_quantity": quantity, "lots": lots,
        "investment": investment, "position_risk_inr": total_risk, "capital_available": round(float(capital), 2),
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
    trade["trade_id"] = str(trade_id or uuid.uuid4())
    trade["opened_at"] = now_utc()
    claimed, reason = claim_contract(
        trade["contract"], trade["symbol"], trade["trade_id"], trade
    )
    if not claimed:
        return {"status": "NO TRADE", "reason": f"ACTIVE POSITION GUARD: {reason}"}
    if not defer_open_event:
        # Persist the complete recoverable payload as ACTIVE before writing
        # lifecycle telemetry. A crash between these operations is recoverable.
        from src.active_position_guard import mark_claim_active
        mark_claim_active(trade["contract"], trade["trade_id"], trade)
        record_event(
            trade, "OPEN", ts=trade["opened_at"], entry=entry, quantity=quantity,
            investment=investment, stop_loss=stop_loss, target1=target1, target2=target2,
            detected_at=trade.get("detected_at") or None,
        )
    return trade
