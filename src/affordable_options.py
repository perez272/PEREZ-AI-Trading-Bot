from __future__ import annotations

from datetime import date, datetime

from src.option_chain import load_instruments
from src.upgrade_config import OPTION_MAX_PREMIUM

INDEX_OPTION_EXCHANGES = {
    "SENSEX": "BFO",
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
}


def _parse_expiry(value):
    try:
        return datetime.strptime(str(value).strip().upper(), "%d%b%Y").date()
    except (TypeError, ValueError):
        return None


def _candidates(symbol: str, spot: float, option_type: str):
    rows = []
    exchange = INDEX_OPTION_EXCHANGES.get(symbol.upper().strip(), "NFO")
    for item in load_instruments():
        if str(item.get("name", "")).upper().strip() != symbol.upper().strip():
            continue
        if str(item.get("exch_seg", "")).upper().strip() != exchange:
            continue
        if str(item.get("instrumenttype", "")).upper().strip() not in ("OPTSTK", "OPTIDX"):
            continue
        option_symbol = str(item.get("symbol", "")).upper().strip()
        if not option_symbol.endswith(option_type.upper()):
            continue
        expiry_date = _parse_expiry(item.get("expiry"))
        try:
            strike = float(item.get("strike", 0)) / 100.0
            lot_size = int(float(item.get("lotsize", 0)))
        except (TypeError, ValueError):
            continue
        if expiry_date is None or expiry_date < date.today() or strike <= 0 or lot_size <= 0:
            continue
        rows.append({
            "symbol": option_symbol,
            "token": str(item.get("token", "")),
            "exchange": exchange,
            "expiry": expiry_date.strftime("%d%b%Y").upper(),
            "expiry_date": expiry_date,
            "strike": strike,
            "lotsize": lot_size,
            "difference": abs(strike - float(spot)),
        })
    rows.sort(key=lambda x: (x["expiry_date"], x["difference"]))
    return rows


def find_affordable_contract(
    symbol: str,
    spot: float,
    option_type: str,
    ltp_getter,
    max_premium: float = OPTION_MAX_PREMIUM,
    batch_ltp_getter=None,
):
    """Find an affordable live-priced option using the nearest true expiry."""
    rows = _candidates(symbol, spot, option_type)
    if not rows:
        return {"status": "NO CONTRACT", "reason": "No valid index/stock option contracts"}

    nearest_expiry = min(r["expiry_date"] for r in rows)
    rows = [r for r in rows if r["expiry_date"] == nearest_expiry]
    rows.sort(key=lambda x: x["difference"])
    rows = rows[:24]

    quotes = {}
    if batch_ltp_getter is not None:
        try:
            quotes = batch_ltp_getter(rows[0]["exchange"], rows) or {}
        except Exception as exc:
            print(f"[OPTION BATCH] {type(exc).__name__}: {exc}")

    affordable = []
    for row in rows:
        try:
            if row["symbol"] in quotes:
                ltp = float(quotes[row["symbol"]])
            else:
                ltp = float(ltp_getter(row["exchange"], row["symbol"], row["token"]))
        except (TypeError, ValueError, Exception):
            continue
        if ltp <= 0 or ltp > max_premium:
            continue
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
