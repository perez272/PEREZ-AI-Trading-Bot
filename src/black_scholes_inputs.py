"""Automatic, provenance-preserving BSM inputs for shadow analytics.

This module is deliberately isolated from strategy, sizing, risk and execution.
Rates are continuously compounded annual decimals; dividend yields are annual
decimals. Missing/stale inputs fail closed.

Source policy:
- FBIL/CCIL can be supplied as authorized provider callables. Their data is not
  scraped by default; verify subscription/licensing before enabling commercial use.
- RBI's published last-auction 91/182/364-day T-bill cut-off yields are fallback
  proxies, not a continuous zero curve.
- NSE index-performance dividend yields are index-specific observations.
"""
from __future__ import annotations

import html
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests

LOG = logging.getLogger("PEREZ.BSM_INPUTS")
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

RBI_URL = "https://m.rbi.org.in/Scripts/BS_LAF_Search.aspx"
NSE_URL = "https://www.nseindia.com/market-data/index-performances"
HTTP_TIMEOUT_SECONDS = 7
RBI_MAX_AGE_DAYS = 14
NSE_MAX_AGE_DAYS = 3
CACHE_SCHEMA_VERSION = 1

INDEX_NAMES = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "FINNIFTY": "NIFTY FINANCIAL SERVICES",
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
    "NIFTYNXT50": "NIFTY NEXT 50",
}


@dataclass(frozen=True)
class ObservedInput:
    value: float
    source: str
    observation_date: date
    retrieved_at: datetime
    units: str
    tenor_days: int | None = None
    fallback_level: str = "PRIMARY"


@dataclass(frozen=True)
class BSMInputs:
    underlying: str
    expiry_date: date
    risk_free_rate: float
    dividend_yield: float
    risk_free_source: str
    risk_free_observation_date: date
    risk_free_tenor_days: int
    dividend_source: str
    dividend_observation_date: date
    retrieved_at: datetime

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("expiry_date", "risk_free_observation_date",
                    "dividend_observation_date"):
            result[key] = result[key].isoformat()
        result["retrieved_at"] = self.retrieved_at.isoformat()
        return result


class _TextAndTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        value = html.unescape(data)
        if value.strip():
            self.text_parts.append(value.strip())
        if self._cell is not None:
            self._cell.append(value)


def _parse_observation_date(text: str) -> date:
    patterns = (
        r"(?:as\s+on|as\s+at\s+[^\n]{0,30}?of)\s*"
        r"(\d{1,2}[- ][A-Za-z]{3,9}[- ,]+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw = re.sub(r"\s+", " ", match.group(1)).replace(",", "")
        for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
                    "%d %B %Y", "%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                pass
    raise ValueError("SOURCE_OBSERVATION_DATE_NOT_FOUND")


def _parse_rbi_tbill_yields(page: str) -> tuple[date, dict[int, float]]:
    parser = _TextAndTableParser()
    parser.feed(page)
    text = " ".join(parser.text_parts)
    observed = _parse_observation_date(text)
    yields: dict[int, float] = {}
    for days in (91, 182, 364):
        match = re.search(
            rf"\b{days}\s*[- ]?day\s+T[- ]?bills?\s*[:|]?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
            text, flags=re.IGNORECASE,
        )
        if match:
            rate_percent = float(match.group(1))
            if 0.0 < rate_percent < 30.0:
                yields[days] = rate_percent / 100.0
    if not yields:
        raise ValueError("RBI_TBILL_YIELDS_NOT_FOUND")
    return observed, yields


def _parse_nse_dividend_yields(page: str) -> tuple[date, dict[str, float]]:
    parser = _TextAndTableParser()
    parser.feed(page)
    text = " ".join(parser.text_parts)
    observed = _parse_observation_date(text)
    output: dict[str, float] = {}
    aliases = {v.upper(): k for k, v in INDEX_NAMES.items()}
    for row in parser.rows:
        if len(row) < 6:
            continue
        name = " ".join(row[0].upper().split())
        key = aliases.get(name)
        if not key:
            continue
        raw = row[-1].replace(",", "").replace("%", "").strip()
        try:
            percent = float(raw)
        except ValueError:
            continue
        if 0.0 <= percent <= 20.0:
            output[key] = percent / 100.0
    if not output:
        raise ValueError("NSE_INDEX_DIVIDEND_YIELDS_NOT_FOUND")
    return observed, output


def _now_ist(now: datetime | None = None) -> datetime:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    return current.astimezone(IST)


def _check_freshness(observed: date, today: date, max_age_days: int) -> None:
    age = (today - observed).days
    if age < 0:
        raise ValueError("SOURCE_OBSERVATION_DATE_IN_FUTURE")
    if age > max_age_days:
        raise ValueError("SOURCE_OBSERVATION_STALE")


def _validate_observed(value: Any, source: str, units: str,
                       observed: date, retrieved: datetime,
                       max_age_days: int, today: date,
                       tenor_days: int | None = None,
                       fallback_level: str = "PRIMARY") -> ObservedInput:
    number = float(value)
    if not 0.0 <= number <= 0.30:
        raise ValueError("INPUT_VALUE_OUT_OF_RANGE")
    _check_freshness(observed, today, max_age_days)
    return ObservedInput(number, source, observed, retrieved, units,
                         tenor_days, fallback_level)


class BSMInputResolver:
    """Resolve and cache safe, auditable inputs; no trading-system side effects.

    Optional FBIL/CCIL providers must return ObservedInput-compatible mappings:
    {value, source, observation_date, units, tenor_days}. Providers are called
    in FBIL -> CCIL order and must be authorized by the data owner.
    """

    def __init__(
        self,
        db_path: str | Path = "data/bsm_input_cache.sqlite3",
        *,
        session: requests.Session | None = None,
        fbil_provider: Callable[[int], dict[str, Any] | None] | None = None,
        ccil_provider: Callable[[int], dict[str, Any] | None] | None = None,
        rbi_url: str = RBI_URL,
        nse_url: str = NSE_URL,
        timeout: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.fbil_provider = fbil_provider
        self.ccil_provider = ccil_provider
        self.rbi_url, self.nse_url, self.timeout = rbi_url, nse_url, timeout
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bsm_input_cache (
                    input_key TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    source TEXT NOT NULL,
                    observation_date TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    units TEXT NOT NULL,
                    tenor_days INTEGER,
                    fallback_level TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bsm_input_source "
                         "ON bsm_input_cache(source, observation_date)")

    def _http_get(self, url: str) -> str:
        response = self.session.get(
            url, timeout=self.timeout,
            headers={"User-Agent": "PEREZ-AI-BSM-Shadow/1.0",
                     "Accept": "text/html,application/xhtml+xml"},
        )
        response.raise_for_status()
        return response.text

    def _store(self, key: str, item: ObservedInput) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO bsm_input_cache
                (input_key,value,source,observation_date,retrieved_at,units,
                 tenor_days,fallback_level,schema_version)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(input_key) DO UPDATE SET
                  value=excluded.value, source=excluded.source,
                  observation_date=excluded.observation_date,
                  retrieved_at=excluded.retrieved_at, units=excluded.units,
                  tenor_days=excluded.tenor_days,
                  fallback_level=excluded.fallback_level,
                  schema_version=excluded.schema_version
            """, (key, item.value, item.source, item.observation_date.isoformat(),
                  item.retrieved_at.isoformat(), item.units, item.tenor_days,
                  item.fallback_level, CACHE_SCHEMA_VERSION))

    def _cached(self, key: str, now: datetime, max_age: int) -> ObservedInput | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bsm_input_cache WHERE input_key=? AND schema_version=?",
                (key, CACHE_SCHEMA_VERSION),
            ).fetchone()
        if row is None:
            return None
        try:
            observed = date.fromisoformat(row["observation_date"])
            _check_freshness(observed, now.date(), max_age)
            retrieved = datetime.fromisoformat(row["retrieved_at"])
            if retrieved.tzinfo is None:
                raise ValueError("CACHE_RETRIEVAL_TIME_NAIVE")
            return ObservedInput(
                float(row["value"]), row["source"], observed, retrieved,
                row["units"], row["tenor_days"], row["fallback_level"],
            )
        except (ValueError, TypeError):
            return None

    def _get_rbi_rates(self, now: datetime) -> tuple[date, dict[int, float]]:
        page = self._http_get(self.rbi_url)
        observed, rates = _parse_rbi_tbill_yields(page)
        _check_freshness(observed, now.date(), RBI_MAX_AGE_DAYS)
        return observed, rates

    def _get_nse_yields(self, now: datetime) -> tuple[date, dict[str, float]]:
        page = self._http_get(self.nse_url)
        observed, yields = _parse_nse_dividend_yields(page)
        _check_freshness(observed, now.date(), NSE_MAX_AGE_DAYS)
        return observed, yields

    @staticmethod
    def _nearest_tenor(expiry_days: int) -> int:
        return min((91, 182, 364), key=lambda tenor: abs(tenor - expiry_days))

    def _authorized_provider_rate(self, provider: Callable[[int], dict[str, Any] | None],
                                  tenor: int, source_name: str,
                                  now: datetime) -> ObservedInput | None:
        raw = provider(tenor)
        if not raw:
            return None
        observed_raw = raw.get("observation_date")
        observed = observed_raw if isinstance(observed_raw, date) else date.fromisoformat(str(observed_raw))
        retrieved = now
        units = str(raw.get("units", "")).lower()
        value = float(raw["value"])
        if units in {"percent", "%", "percentage"}:
            value /= 100.0
        elif units not in {"decimal", "annual_decimal"}:
            raise ValueError(f"{source_name}_RATE_UNITS_UNRECOGNIZED")
        actual_tenor = int(raw.get("tenor_days", tenor))
        if abs(actual_tenor - tenor) > max(7, tenor * 0.10):
            raise ValueError(f"{source_name}_TENOR_MISMATCH")
        return _validate_observed(
            value, str(raw.get("source", source_name)), "annual_decimal",
            observed, retrieved, RBI_MAX_AGE_DAYS, now.date(),
            actual_tenor, source_name.upper(),
        )

    def resolve(self, underlying: str, expiry: Any,
                *, now: datetime | None = None) -> BSMInputs:
        current = _now_ist(now)
        symbol = str(underlying).strip().upper()
        if symbol not in INDEX_NAMES:
            raise ValueError("UNSUPPORTED_INDEX_FOR_DIVIDEND_YIELD")
        expiry_date = expiry.date() if isinstance(expiry, datetime) else (
            expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
        )
        expiry_days = (expiry_date - current.date()).days
        if expiry_days <= 0:
            raise ValueError("EXPIRY_NOT_IN_FUTURE")
        tenor = self._nearest_tenor(expiry_days)
        retrieved = current.astimezone(UTC)

        rate_item: ObservedInput | None = None
        provider_errors: list[str] = []
        for name, provider in (("FBIL", self.fbil_provider), ("CCIL", self.ccil_provider)):
            if provider is None:
                continue
            try:
                rate_item = self._authorized_provider_rate(provider, tenor, name, current)
                if rate_item is not None:
                    break
            except Exception as exc:
                provider_errors.append(f"{name}:{exc}")
                LOG.warning("BSM rate provider unavailable | %s", provider_errors[-1])

        if rate_item is None:
            try:
                observed, rates = self._get_rbi_rates(current)
                if tenor not in rates:
                    raise ValueError(f"RBI_TBILL_TENOR_{tenor}_NOT_AVAILABLE")
                rate_item = _validate_observed(
                    rates[tenor], "RBI_LAST_AUCTION_TBILL_PROXY",
                    "annual_decimal", observed, retrieved,
                    RBI_MAX_AGE_DAYS, current.date(), tenor, "RBI_FALLBACK",
                )
            except Exception as exc:
                provider_errors.append(f"RBI:{exc}")
                cached = self._cached(f"RBI_TBILL_{tenor}", current, RBI_MAX_AGE_DAYS)
                if cached is None:
                    raise ValueError("SKIPPED_INPUT_UNAVAILABLE:RISK_FREE_RATE:" +
                                     "|".join(provider_errors)) from exc
                rate_item = cached
            else:
                self._store(f"RBI_TBILL_{tenor}", rate_item)

        try:
            observed, yields = self._get_nse_yields(current)
            if symbol not in yields:
                raise ValueError(f"NSE_DIVIDEND_YIELD_MISSING:{symbol}")
            dividend_item = _validate_observed(
                yields[symbol], "NSE_INDEX_PERFORMANCE", "annual_decimal",
                observed, retrieved, NSE_MAX_AGE_DAYS, current.date(),
                None, "INDEX_SPECIFIC",
            )
        except Exception as exc:
            cached = self._cached(f"NSE_DIVIDEND_{symbol}", current, NSE_MAX_AGE_DAYS)
            if cached is None:
                raise ValueError(f"SKIPPED_INPUT_UNAVAILABLE:DIVIDEND_YIELD:{symbol}:{exc}") from exc
            dividend_item = cached
        else:
            self._store(f"NSE_DIVIDEND_{symbol}", dividend_item)

        return BSMInputs(
            underlying=symbol,
            expiry_date=expiry_date,
            risk_free_rate=rate_item.value,
            dividend_yield=dividend_item.value,
            risk_free_source=rate_item.source,
            risk_free_observation_date=rate_item.observation_date,
            risk_free_tenor_days=rate_item.tenor_days or tenor,
            dividend_source=dividend_item.source,
            dividend_observation_date=dividend_item.observation_date,
            retrieved_at=retrieved,
        )
