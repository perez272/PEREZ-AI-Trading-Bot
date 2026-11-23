"""Observation-only expiry and option-chain intelligence.

No trade eligibility, order, sizing, or risk decisions are made here.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "memory" / "expiry_oi_shadow.sqlite3"
IST = ZoneInfo("Asia/Kolkata")
DELTA_MIN = 0.45
DELTA_MAX = 0.60
LATE_0DTE_CUTOFF = time(14, 15)
PIN_WINDOW_START = time(11, 30)
PIN_WINDOW_END = time(13, 30)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _local_datetime(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(IST)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def expiry_class(expiry: str | date, observed_at: str | datetime | None = None) -> dict[str, Any]:
    now = _local_datetime(observed_at)
    expiry_date = expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
    days = (expiry_date - now.date()).days
    return {"expiry": expiry_date.isoformat(), "dte": days,
            "bucket": "0DTE" if days == 0 else "1DTE" if days == 1 else "OTHER" if days > 1 else "EXPIRED"}


def _strike_step(strikes: list[float]) -> float | None:
    ordered = sorted(set(strikes))
    gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
    return min(gaps) if gaps else None


def _leg(row: dict[str, Any], side: str) -> dict[str, Any]:
    option = row.get("call_options" if side == "CE" else "put_options") or {}
    market = option.get("market_data") or {}
    greeks = option.get("option_greeks") or {}
    return {
        "instrument_key": option.get("instrument_key"),
        "ltp": _number(market.get("ltp")),
        "oi": _number(market.get("oi")),
        "volume": _number(market.get("volume")),
        "delta": _number(greeks.get("delta")),
        "gamma": _number(greeks.get("gamma")),
        "lot_size": _number(option.get("lot_size") or row.get("lot_size")),
    }


def _validate_chain(chain: list[dict[str, Any]], observed_at: str | datetime | None) -> list[str]:
    """Fail closed unless the snapshot has enough internally consistent evidence."""
    now = _local_datetime(observed_at)
    reasons: list[str] = []
    rows = [row for row in (chain or []) if isinstance(row, dict)]
    if len(rows) != len(chain or []):
        reasons.append("MALFORMED_CHAIN_ROW")
    strikes = {_number(row.get("strike_price")) for row in rows}
    strikes.discard(None)
    if len(strikes) < 5:
        reasons.append("INSUFFICIENT_STRIKE_COVERAGE")
    expiries = []
    spots = []
    for row in rows:
        try:
            expiry = date.fromisoformat(str(row.get("expiry") or "")[:10])
        except (TypeError, ValueError):
            reasons.append("MISSING_OR_INVALID_EXPIRY")
            expiry = None
        if expiry is not None:
            expiries.append(expiry)
        spot = _number(row.get("underlying_spot_price") or row.get("underlying_spot"))
        if spot is not None and spot > 0:
            spots.append(spot)
        for side in ("CE", "PE"):
            option = row.get("call_options" if side == "CE" else "put_options")
            market = option.get("market_data") if isinstance(option, dict) else None
            key = option.get("instrument_key") if isinstance(option, dict) else None
            ltp = _number(market.get("ltp")) if isinstance(market, dict) else None
            oi = _number(market.get("oi")) if isinstance(market, dict) else None
            if not key or ltp is None or ltp <= 0 or oi is None or oi < 0:
                reasons.append("INCOMPLETE_OPTION_LEG")
                break
    if not spots:
        reasons.append("MISSING_UNDERLYING_SPOT")
    if expiries:
        if len(set(expiries)) != 1:
            reasons.append("MIXED_EXPIRIES")
        if min(expiries) < now.date():
            reasons.append("EXPIRED_CONTRACTS")
    if spots and strikes and not (min(strikes) <= median(spots) <= max(strikes)):
        reasons.append("SPOT_OUTSIDE_STRIKE_COVERAGE")
    return sorted(set(reasons))


def analyze_chain(
    symbol: str,
    chain: list[dict[str, Any]],
    observed_at: str | datetime | None = None,
    previous: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize a timestamped chain only after strict evidence validation."""
    now = _local_datetime(observed_at)
    previous = previous or {}
    quality_reasons = _validate_chain(chain, now)
    if quality_reasons:
        return {
            "symbol": str(symbol).upper(), "observed_at": now.isoformat(),
            "spot": None, "expiry": None, "dte": None, "expiry_bucket": "UNKNOWN",
            "strike_step": None, "atm_strike": None, "candidates": [],
            "oi_evidence": [], "highest_combined_oi_strike": None,
            "highest_combined_oi": None, "oi_chain_complete": False,
            "max_pain_strike": None, "max_pain_payout": None,
            "pinning_window": False, "pinning_candidate": False,
            "breakout_status": "INSUFFICIENT_OI_DATA", "breakout_confirmed": False,
            "oi_direction": "NO_CONFIRMED_OI_PATTERN",
            "oi_note": "Snapshot rejected: " + ", ".join(quality_reasons),
            "late_0dte_cutoff": False, "safety": "OBSERVATION_ONLY",
            "data_quality_status": "REJECTED", "data_quality_reasons": quality_reasons,
        }
    rows = []
    strikes = []
    spots = []
    expiries = []
    for row in chain or []:
        strike = _number(row.get("strike_price"))
        expiry = row.get("expiry")
        spot = _number(row.get("underlying_spot_price") or row.get("underlying_spot"))
        if strike is None or strike <= 0:
            continue
        strikes.append(strike)
        if spot is not None and spot > 0:
            spots.append(spot)
        if expiry:
            expiries.append(str(expiry)[:10])
        for side in ("CE", "PE"):
            leg = _leg(row, side)
            key = str(leg["instrument_key"] or "")
            old = previous.get(key) if key else None
            if old and not old.get("observed_at"):
                old = None
            if old and old.get("observed_at"):
                try:
                    age = (now - _local_datetime(old["observed_at"])).total_seconds()
                    if age < 0 or age > 120:
                        old = None
                except (TypeError, ValueError):
                    old = None
            leg.update({"side": side, "strike": strike, "expiry": str(expiry)[:10] if expiry else None})
            leg["oi_change"] = (leg["oi"] - _number(old.get("oi"))
                                if old and leg["oi"] is not None and _number(old.get("oi")) is not None else None)
            leg["premium_change"] = (leg["ltp"] - _number(old.get("ltp"))
                                     if old and leg["ltp"] is not None and _number(old.get("ltp")) is not None else None)
            rows.append(leg)
    spot = median(spots) if spots else None
    step = _strike_step(strikes)
    expiry = min(expiries) if expiries else None
    expiry_info = expiry_class(expiry, now) if expiry else {"expiry": None, "dte": None, "bucket": "UNKNOWN"}

    combined: dict[float, float] = {}
    for strike in strikes:
        combined[strike] = 0.0
    for leg in rows:
        if leg["oi"] is not None:
            combined[leg["strike"]] += leg["oi"]
    oi_chain_complete = bool(rows) and all(x["oi"] is not None for x in rows)
    highest = max(combined, key=combined.get) if combined and oi_chain_complete else None
    call_oi = {x["strike"]: x["oi"] for x in rows if x["side"] == "CE" and x["oi"] is not None}
    put_oi = {x["strike"]: x["oi"] for x in rows if x["side"] == "PE" and x["oi"] is not None}
    settlement_costs = {
        settlement: sum(max(settlement - strike, 0.0) * oi for strike, oi in call_oi.items())
        + sum(max(strike - settlement, 0.0) * oi for strike, oi in put_oi.items())
        for settlement in strikes
    }
    max_pain = min(settlement_costs, key=settlement_costs.get) if settlement_costs and oi_chain_complete else None

    candidates = []
    if spot is not None and step:
        atm = min(strikes, key=lambda value: abs(value - spot))
        for side in ("CE", "PE"):
            target = atm - step if side == "CE" else atm + step
            candidate_strikes = {atm, min(strikes, key=lambda value: abs(value - target))}
            for leg in rows:
                if leg["side"] == side and leg["strike"] in candidate_strikes:
                    delta = abs(leg["delta"]) if leg["delta"] is not None else None
                    candidates.append({
                        "side": side, "strike": leg["strike"], "ltp": leg["ltp"],
                        "delta": delta, "volume": leg["volume"], "oi": leg["oi"],
                        "delta_in_band": DELTA_MIN <= delta <= DELTA_MAX if delta is not None else None,
                        "instrument_key": leg["instrument_key"],
                        "gamma": leg["gamma"], "lot_size": leg["lot_size"],
                    })

    near_rows = [x for x in rows if spot is not None and step is not None and abs(x["strike"] - spot) <= 2 * step]
    call_unwind = any(x["side"] == "CE" and x["oi_change"] is not None and x["oi_change"] < 0
                      and x["premium_change"] is not None and x["premium_change"] > 0 for x in near_rows)
    put_unwind = any(x["side"] == "PE" and x["oi_change"] is not None and x["oi_change"] < 0
                     and x["premium_change"] is not None and x["premium_change"] > 0 for x in near_rows)
    put_build = any(x["side"] == "PE" and x["oi_change"] is not None and x["oi_change"] > 0 for x in near_rows)
    call_build = any(x["side"] == "CE" and x["oi_change"] is not None and x["oi_change"] > 0 for x in near_rows)
    old_spots = [_number(x.get("spot")) for x in previous.values() if x.get("observed_at") and _number(x.get("spot")) is not None and 0 <= (now - _local_datetime(x["observed_at"])).total_seconds() <= 120]
    old_spot = median(old_spots) if old_spots else None
    spot_up = spot is not None and old_spot is not None and spot > old_spot
    spot_down = spot is not None and old_spot is not None and spot < old_spot
    direction = "BULLISH_OI_PATTERN" if spot_up and call_unwind and put_build else (
        "BEARISH_OI_PATTERN" if spot_down and put_unwind and call_build else "NO_CONFIRMED_OI_PATTERN")

    # A clean breakout is observational only: require two consecutive fresh
    # snapshots beyond the current highest-combined-OI wall, continued spot
    # progress, and matching OI/premium direction confirmation.
    wall_upper = highest + step / 2 if highest is not None and step is not None else None
    wall_lower = highest - step / 2 if highest is not None and step is not None else None
    up_breakout = bool(wall_upper is not None and spot is not None and old_spot is not None
                       and old_spot > wall_upper and spot > wall_upper and spot > old_spot
                       and direction == "BULLISH_OI_PATTERN")
    down_breakout = bool(wall_lower is not None and spot is not None and old_spot is not None
                         and old_spot < wall_lower and spot < wall_lower and spot < old_spot
                         and direction == "BEARISH_OI_PATTERN")
    breakout_status = ("UP_BREAKOUT_CONFIRMED" if up_breakout else
                       "DOWN_BREAKOUT_CONFIRMED" if down_breakout else
                       "NOT_CONFIRMED" if highest is not None else "INSUFFICIENT_OI_DATA")

    local_time = now.timetz().replace(tzinfo=None)
    midday = PIN_WINDOW_START <= local_time <= PIN_WINDOW_END
    pinned = bool(midday and spot is not None and highest is not None and step is not None
                  and abs(spot - highest) <= step / 2)
    late = expiry_info["bucket"] == "0DTE" and local_time >= LATE_0DTE_CUTOFF

    return {
        "symbol": str(symbol).upper(), "observed_at": now.isoformat(), "spot": spot,
        "expiry": expiry_info["expiry"], "dte": expiry_info["dte"], "expiry_bucket": expiry_info["bucket"],
        "strike_step": step, "atm_strike": min(strikes, key=lambda value: abs(value - spot)) if spot is not None and strikes else None,
        "candidates": candidates, "oi_evidence": [{"side": x["side"], "strike": x["strike"], "oi": x["oi"], "oi_change": x["oi_change"], "premium": x["ltp"], "premium_change": x["premium_change"], "volume": x["volume"]} for x in rows if x["oi"] is not None], "highest_combined_oi_strike": highest,
        "highest_combined_oi": combined.get(highest) if highest is not None else None,
        "oi_chain_complete": oi_chain_complete,
        "max_pain_strike": max_pain, "max_pain_payout": settlement_costs.get(max_pain) if max_pain is not None else None,
        "pinning_window": midday, "pinning_candidate": pinned,
        "breakout_status": breakout_status,
        "breakout_confirmed": up_breakout or down_breakout,
        "oi_direction": direction,
        "oi_note": ("OI changes are interval-based proxies, not proof of participant intent; premium and spot confirmation are required. " + ("Full-chain OI available." if oi_chain_complete else "Incomplete OI chain: max-pain and concentration metrics are unavailable.")),
        "late_0dte_cutoff": late, "safety": "OBSERVATION_ONLY",
        "data_quality_status": "VALID", "data_quality_reasons": [],
    }


def record_chain_snapshot(
    symbol: str, chain: list[dict[str, Any]], observed_at: str | datetime | None = None,
    db_path: Path = DEFAULT_DB,
) -> dict[str, Any]:
    now = _local_datetime(observed_at)
    result = analyze_chain(symbol, chain, now)
    if result.get("data_quality_status") != "VALID":
        reasons = ", ".join(result.get("data_quality_reasons") or ["INVALID_CHAIN"])
        raise ValueError(f"Expiry/OI snapshot rejected for {symbol}: {reasons}")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    for row in chain or []:
        spot = _number(row.get("underlying_spot_price") or row.get("underlying_spot"))
        for side in ("CE", "PE"):
            leg = _leg(row, side)
            key = str(leg["instrument_key"] or "")
            if key and leg["oi"] is not None:
                current[key] = {"oi": leg["oi"], "ltp": leg["ltp"], "spot": spot}
    previous = {}
    with sqlite3.connect(db_path, timeout=3) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS chain_snapshots (
            instrument_key TEXT NOT NULL, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
            oi REAL, ltp REAL, spot REAL, PRIMARY KEY(instrument_key, observed_at))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
            observed_at TEXT NOT NULL, payload_json TEXT NOT NULL)""")
        for key in current:
            row = conn.execute(
                "SELECT oi,ltp,spot,observed_at FROM chain_snapshots WHERE instrument_key=? ORDER BY observed_at DESC LIMIT 1",
                (key,),
            ).fetchone()
            if row:
                previous[key] = {"oi": row[0], "ltp": row[1], "spot": row[2], "observed_at": row[3]}
        result = analyze_chain(symbol, chain, now, previous)
        for key, item in current.items():
            conn.execute("INSERT OR REPLACE INTO chain_snapshots VALUES (?,?,?,?,?,?)",
                         (key, str(symbol).upper(), now.isoformat(), item["oi"], item["ltp"], item["spot"]))
        conn.execute("INSERT INTO observations(symbol,observed_at,payload_json) VALUES (?,?,?)",
                     (str(symbol).upper(), now.isoformat(), json.dumps(result, separators=(",", ":"))))
        conn.execute("""DELETE FROM observations WHERE id NOT IN
                        (SELECT id FROM observations ORDER BY id DESC LIMIT 500)""")
        conn.execute("""DELETE FROM chain_snapshots WHERE rowid NOT IN
                        (SELECT rowid FROM chain_snapshots ORDER BY observed_at DESC LIMIT 30000)""")
    return result


def latest_observations(
    db_path: Path = DEFAULT_DB, limit: int = 30,
    max_age_seconds: int = 120, now: str | datetime | None = None,
) -> list[dict[str, Any]]:
    """Return only each symbol's latest validated, non-expired, fresh snapshot."""
    if not Path(db_path).exists():
        return []
    current_time = _local_datetime(now)
    try:
        with sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True, timeout=2) as conn:
            rows = conn.execute("""SELECT payload_json FROM observations AS o WHERE id IN
                                 (SELECT MAX(id) FROM observations GROUP BY symbol)
                                 ORDER BY id DESC LIMIT ?""",
                                 (max(1, min(int(limit), 100)),)).fetchall()
        result = []
        for row in rows:
            item = json.loads(row[0])
            if item.get("data_quality_status") != "VALID":
                continue
            try:
                observed = _local_datetime(item.get("observed_at"))
                age = (current_time - observed).total_seconds()
                expiry = date.fromisoformat(str(item.get("expiry") or "")[:10])
            except (TypeError, ValueError):
                continue
            if age < 0 or age > max(0, int(max_age_seconds)) or expiry < current_time.date():
                continue
            result.append(item)
        return result
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return []
