from src.deep_value_scanner import Holding, HiddenValueInput, analyze_hidden_value


def test_elcid_style_nav_and_discount():
    item = HiddenValueInput(
        company="SELFTEST",
        shares_outstanding=200_000,
        market_price=10_000,
        holdings=(Holding("Major Holding", 10_000_000, 1_000),),
        cash_cr=100,
        debt_cr=50,
        deferred_tax_cr=25,
        uncalled_commitment_cr=25,
        holding_company_discount_pct=20,
    )
    result = analyze_hidden_value(item)
    assert result.market_cap_cr == 200.0
    assert result.conservative_nav_cr > result.market_cap_cr
    assert result.base_nav_cr > result.market_cap_cr
    assert 0 <= result.score <= 100
    assert result.verdict in {"DEEP VALUE", "WATCH", "FAIR VALUE", "AVOID"}


def test_invalid_shares_rejected():
    try:
        analyze_hidden_value(HiddenValueInput(company="BAD", shares_outstanding=0, market_price=1))
    except ValueError:
        return
    raise AssertionError("zero shares_outstanding must be rejected")
