from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.black_scholes_inputs import (
    BSMInputResolver,
    calculate_chain_greeks_with_resolved_inputs,
    INDEX_NAMES,
    _parse_nse_dividend_yields,
    _parse_rbi_tbill_yields,
)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=IST)

RBI_HTML = """
<html><body>
<h2>Government Securities Market</h2>
<p>91 day T-bills | : 5.25%*</p>
<p>182 day T-bills | : 5.50%*</p>
<p>364 day T-bills | : 5.70%*</p>
<p>* cut-off at the last auction</p>
<p>as on November 02, 2026</p>
</body></html>
"""

NSE_HTML = """
<html><body>
<p>As on 02-Nov-2026 15:30 IST</p>
<table>
<tr><th>Index Name</th><th>Last</th><th>Change</th><th>%change</th><th>P/E</th><th>P/B</th><th>Div yield</th></tr>
<tr><td>NIFTY 50</td><td>24000</td><td>0</td><td>0</td><td>20</td><td>3</td><td>1.49</td></tr>
<tr><td>NIFTY BANK</td><td>55000</td><td>0</td><td>0</td><td>13</td><td>2</td><td>1.14</td></tr>
<tr><td>NIFTY FINANCIAL SERVICES</td><td>25000</td><td>0</td><td>0</td><td>15</td><td>2</td><td>1.01</td></tr>
<tr><td>NIFTY MIDCAP SELECT</td><td>13000</td><td>0</td><td>0</td><td>27</td><td>4</td><td>0.80</td></tr>
<tr><td>NIFTY NEXT 50</td><td>67000</td><td>0</td><td>0</td><td>18</td><td>3</td><td>1.51</td></tr>
</table></body></html>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kwargs):
        return FakeResponse(self.pages[url])


def resolver(tmp_path, fbil=None, ccil=None):
    return BSMInputResolver(
        tmp_path / "cache.sqlite3",
        session=FakeSession({"rbi": RBI_HTML, "nse": NSE_HTML}),
        fbil_provider=fbil, ccil_provider=ccil,
        rbi_url="rbi", nse_url="nse",
    )


def test_rbi_parser_converts_percent_to_decimal():
    observed, rates = _parse_rbi_tbill_yields(RBI_HTML)
    assert observed == date(2026, 11, 2)
    assert rates == pytest.approx({91: 0.0525, 182: 0.055, 364: 0.057})


def test_nse_parser_returns_distinct_index_yields():
    observed, yields = _parse_nse_dividend_yields(NSE_HTML)
    assert observed == date(2026, 11, 2)
    assert set(yields) == set(INDEX_NAMES)
    assert yields["NIFTY"] == pytest.approx(0.0149)
    assert yields["BANKNIFTY"] == pytest.approx(0.0114)
    assert yields["MIDCPNIFTY"] == pytest.approx(0.008)


@pytest.mark.parametrize("symbol", list(INDEX_NAMES))
def test_resolve_uses_rbi_and_matching_index_dividend(tmp_path, symbol):
    r = resolver(tmp_path)
    result = r.resolve(symbol, date(2026, 12, 15), now=NOW)
    assert result.underlying == symbol
    assert result.risk_free_rate == pytest.approx(0.0525)
    assert result.dividend_yield > 0
    assert result.risk_free_source == "RBI_LAST_AUCTION_TBILL_PROXY"
    assert result.risk_free_tenor_days == 91  # expiry is 42 days away
    assert result.dividend_source == "NSE_INDEX_PERFORMANCE"


def test_authorized_fbil_provider_has_priority(tmp_path):
    def fbil(tenor):
        return {"value": 6.1, "units": "percent",
                "observation_date": "2026-11-02", "tenor_days": tenor}
    result = resolver(tmp_path, fbil=fbil).resolve("NIFTY", "2026-12-03", now=NOW)
    assert result.risk_free_rate == pytest.approx(0.061)
    assert result.risk_free_source == "FBIL"


def test_ccil_is_used_when_fbil_provider_fails(tmp_path):
    def fbil(_):
        raise RuntimeError("offline")
    def ccil(tenor):
        return {"value": 0.058, "units": "decimal",
                "observation_date": "2026-11-02", "tenor_days": tenor}
    result = resolver(tmp_path, fbil=fbil, ccil=ccil).resolve(
        "BANKNIFTY", "2026-12-03", now=NOW
    )
    assert result.risk_free_rate == pytest.approx(0.058)
    assert result.risk_free_source == "CCIL"


def test_stale_rbi_data_fails_closed(tmp_path):
    stale = RBI_HTML.replace("November 02, 2026", "October 01, 2026")
    r = BSMInputResolver(
        tmp_path / "cache.sqlite3",
        session=FakeSession({"rbi": stale, "nse": NSE_HTML}),
        rbi_url="rbi", nse_url="nse",
    )
    with pytest.raises(ValueError, match="SKIPPED_INPUT_UNAVAILABLE:RISK_FREE_RATE"):
        r.resolve("NIFTY", "2026-12-03", now=NOW)


def test_stale_nse_data_fails_closed(tmp_path):
    stale = NSE_HTML.replace("02-Nov-2026", "01-Oct-2026")
    r = BSMInputResolver(
        tmp_path / "cache.sqlite3",
        session=FakeSession({"rbi": RBI_HTML, "nse": stale}),
        rbi_url="rbi", nse_url="nse",
    )
    with pytest.raises(ValueError, match="SKIPPED_INPUT_UNAVAILABLE:DIVIDEND_YIELD"):
        r.resolve("NIFTY", "2026-12-03", now=NOW)


def test_fresh_cache_used_when_source_temporarily_unavailable(tmp_path):
    r = resolver(tmp_path)
    first = r.resolve("NIFTY", "2026-12-03", now=NOW)
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise OSError("network down")
    r.session = BrokenSession()
    second = r.resolve("NIFTY", "2026-12-03", now=NOW)
    assert second.risk_free_rate == first.risk_free_rate
    assert second.dividend_yield == first.dividend_yield


def test_unknown_index_and_expired_date_rejected(tmp_path):
    r = resolver(tmp_path)
    with pytest.raises(ValueError, match="UNSUPPORTED_INDEX"):
        r.resolve("SENSEX", "2026-12-03", now=NOW)
    with pytest.raises(ValueError, match="EXPIRY_NOT_IN_FUTURE"):
        r.resolve("NIFTY", "2026-11-02", now=NOW)



def test_calculation_bridge_attaches_input_provenance(tmp_path):
    import pandas as pd
    from src.black_scholes_engine import black_scholes_greeks, time_to_expiry_years

    expiry = date(2026, 12, 3)
    years = time_to_expiry_years(expiry, NOW)
    theoretical = black_scholes_greeks(
        25000, 25000, years, 0.0525, 0.0149, 0.20, "CE"
    )["price"]
    chain = pd.DataFrame([{
        "spot": 25000, "strike": 25000, "expiry": expiry,
        "option_type": "CE", "bid": theoretical - 0.05,
        "ask": theoretical + 0.05,
    }])
    output = calculate_chain_greeks_with_resolved_inputs(
        chain, underlying="NIFTY", expiry=expiry,
        resolver=resolver(tmp_path), now=NOW,
    )
    assert output.loc[0, "bs_status"] == "OK"
    assert output.loc[0, "bs_risk_free_source"] == "RBI_LAST_AUCTION_TBILL_PROXY"
    assert output.loc[0, "bs_dividend_source"] == "NSE_INDEX_PERFORMANCE"
    assert output.loc[0, "bs_risk_free_rate"] == pytest.approx(0.0525)


def test_calculation_bridge_skips_when_inputs_unavailable(tmp_path):
    import pandas as pd

    class NoSources:
        def resolve(self, *args, **kwargs):
            raise ValueError("SKIPPED_INPUT_UNAVAILABLE")

    chain = pd.DataFrame([{"spot": 25000, "strike": 25000}])
    output = calculate_chain_greeks_with_resolved_inputs(
        chain, underlying="NIFTY", expiry="2026-12-03",
        resolver=NoSources(), now=NOW,
    )
    assert output.loc[0, "bs_status"] == "SKIPPED_INPUT_UNAVAILABLE"
    assert "SKIPPED_INPUT_UNAVAILABLE" in output.loc[0, "bs_error"]
