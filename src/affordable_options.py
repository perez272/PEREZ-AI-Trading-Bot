from __future__ import annotations

from datetime import datetime

from src.option_chain import load_instruments
from src.upgrade_config import OPTION_MAX_PREMIUM


def _candidates(symbol: str, spot: float, option_type: str):
    today = datetime.now().date()
    rows = []
    for item in load_instruments():
        if str(item.get("name", "")).upper().strip() != symbol.upper().strip():
            continue
        if str(item.get("exch_seg", "")).upper().strip() != "NFO":
            continue
        if str(item.get("instrumenttype", "")).upper().strip() not in ("OPTSTK", "OPTIDX"):
            continue
        option_symbol = str(item.get("symbol", "")).upper().strip()
        if not option_symbol.endswith(option_type.upper()):
            continue
        try:
            expiry = datetime.strptime(str(item.get("expiry", "")).strip().upper(), "%d%b%Y").date()
            strike = float(item.get("strike", 0)) / 100.0
            lot_size = int(float(item.get("lotsize", 0)))
        except (TypeError, ValueError):
            continue
        if expiry < today or strike <= 0 or lot_size <= 0:
            continue
        rows.append({
            "symbol": option_symbol,
            "token": str(item.get("token", "")),
            "exchange": "NFO",
            "expiry": expiry.strftime("%d%b%Y").upper(),
            "strike": strike,
            "lotsize": lot_size,
            "difference": abs(strike - float(spot)),
        })
    rows.sort(key=lambda x: (x["expiry"], x["difference"]))
    return rows


def find_affordable_contract(
    symbol: str,
    spot: float,
    option_type: str,
    ltp_getter,
    max_premium: float = OPTION_MAX_PREMIUM,
    batch_ltp_getter=None,
):
    """Find a liquid-ish, affordable contract without assuming the ATM option is best."""
    rows = _candidates(symbol, spot, option_type)
    if not rows:
        return {"status": "NO CONTRACT", "reason": "No valid NFO contracts"}

    # Concentrate on the nearest expiry and a practical strike band, then
    # inspect a limited number of strikes to avoid API bursts.
    nearest_expiry = rows[0]["expiry"]
    rows = [r for r in rows if r["expiry"] == nearest_expiry]
    rows.sort(key=lambda x: x["difference"])
    rows = rows[:24]

    affordable = []

    quotes = {}
    if batch_ltp_getter is not None:
        try:
            quotes = batch_ltp_getter("NFO", rows) or {}
        except Exception as exc:
            print(f"[OPTION BATCH] {type(exc).__name__}: {exc}")

    for row in rows:
        try:
            if batch_ltp_getter is not None:
                ltp = float(quotes.get(row["symbol"]))
            else:
                ltp = float(
                    ltp_getter(
                        row["exchange"],
                        row["symbol"],
                        row["token"],
                    )
                )
        except (TypeError, ValueError, Exception):
            continue
        if ltp <= 0 or ltp > max_premium:
            continue
        # Prefer lower premium but keep a strong preference for strikes close
        # enough to the underlying to retain meaningful delta.
        distance_ratio = row["difference"] / max(float(spot), 1.0)
        score = (max_premium - ltp) / max_premium * 55.0 + max(0.0, 1.0 - distance_ratio * 12.0) * 45.0
        affordable.append({**row, "ltp": ltp, "affordability_score": round(score, 2)})

    if not affordable:
        return {"status": "NO AFFORDABLE OPTION", "reason": f"No {option_type} premium <= Rs {max_premium:.2f}"}

    return max(affordable, key=lambda x: x["affordability_score"])


def score_option_quote(quote: dict, underlying_score: float = 0.0) -> float:
    """Score live option evidence; never rewards price alone."""
    score = min(max(float(underlying_score), 0.0), 35.0)
    pct = float(quote.get("percentChange", quote.get("netChange", 0)) or 0)
    volume = float(quote.get("tradeVolume", 0) or 0)
    oi = float(quote.get("opnInterest", 0) or 0)
    buy = float(quote.get("totBuyQuan", 0) or 0)
    sell = float(quote.get("totSellQuan", 0) or 0)
    ltp = float(quote.get("ltp", 0) or 0)
    score += min(max(pct, 0.0) * 2.0, 20.0)
    score += 10.0 if volume > 0 else 0.0
    score += 10.0 if oi > 0 else 0.0
    if buy + sell > 0:
        score += min(max((buy - sell) / (buy + sell), 0.0) * 10.0, 10.0)
    if 0 < ltp <= OPTION_MAX_PREMIUM:
        score += 5.0
    return round(min(score, 100.0), 2)
