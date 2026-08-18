"""ELCID-style deep-value / hidden-NAV analysis.

This module is deliberately separate from the short-term trading engine.
It only calculates from supplied, auditable inputs; it never places orders.
"""
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Holding:
    name: str
    shares: float
    value_per_share: float
    ownership_pct: float | None = None
    liquidity_discount_pct: float = 0.0

    @property
    def gross_value_cr(self) -> float:
        return self.shares * self.value_per_share / 1e7

    @property
    def adjusted_value_cr(self) -> float:
        return self.gross_value_cr * (1 - self.liquidity_discount_pct / 100)


@dataclass(frozen=True)
class HiddenValueInput:
    company: str
    shares_outstanding: float
    market_price: float
    holdings: tuple[Holding, ...] = field(default_factory=tuple)
    cash_cr: float = 0.0
    other_assets_cr: float = 0.0
    debt_cr: float = 0.0
    deferred_tax_cr: float = 0.0
    uncalled_commitment_cr: float = 0.0
    other_liabilities_cr: float = 0.0
    holding_company_discount_pct: float = 0.0


@dataclass(frozen=True)
class HiddenValueResult:
    company: str
    market_cap_cr: float
    gross_asset_value_cr: float
    conservative_nav_cr: float
    base_nav_cr: float
    bull_nav_cr: float
    discount_to_conservative_pct: float
    discount_to_base_pct: float
    margin_of_safety_pct: float
    score: float
    verdict: str
    details: dict


def _discount(market_cap: float, nav: float) -> float:
    if nav <= 0:
        return 0.0
    return (1 - market_cap / nav) * 100


def analyze_hidden_value(item: HiddenValueInput) -> HiddenValueResult:
    if item.shares_outstanding <= 0 or item.market_price < 0:
        raise ValueError("shares_outstanding must be positive and market_price non-negative")

    market_cap_cr = item.shares_outstanding * item.market_price / 1e7
    gross_holdings = sum(h.gross_value_cr for h in item.holdings)
    conservative_holdings = sum(h.adjusted_value_cr for h in item.holdings)

    liabilities = item.debt_cr + item.deferred_tax_cr + item.uncalled_commitment_cr + item.other_liabilities_cr
    base_assets = gross_holdings + item.cash_cr + item.other_assets_cr
    conservative_assets = conservative_holdings + item.cash_cr + item.other_assets_cr

    # Conservative NAV applies both holding liquidity haircuts and the
    # holding-company discount. Base NAV uses supplied fair values without
    # that structural discount. Bull NAV is intentionally a scenario, not a
    # prediction, using the supplied gross holdings.
    structural_factor = max(0.0, 1 - item.holding_company_discount_pct / 100)
    conservative_nav = max(0.0, conservative_assets * structural_factor - liabilities)
    base_nav = max(0.0, base_assets - liabilities)
    bull_nav = max(0.0, base_assets * 1.10 - liabilities)

    discount_cons = _discount(market_cap_cr, conservative_nav)
    discount_base = _discount(market_cap_cr, base_nav)
    margin = discount_cons

    score = 0.0
    if discount_cons >= 70: score += 35
    elif discount_cons >= 50: score += 28
    elif discount_cons >= 30: score += 18
    elif discount_cons >= 15: score += 8
    if conservative_nav > 0 and market_cap_cr / conservative_nav <= 0.5: score += 20
    if liabilities <= base_assets * 0.25: score += 15
    if item.cash_cr > 0: score += 5
    if gross_holdings > 0: score += 10
    if len(item.holdings) >= 2: score += 5
    score = min(score, 100.0)

    if score >= 75 and discount_cons >= 40:
        verdict = "DEEP VALUE"
    elif score >= 50 and discount_cons >= 20:
        verdict = "WATCH"
    elif discount_base > 0:
        verdict = "FAIR VALUE"
    else:
        verdict = "AVOID"

    return HiddenValueResult(
        company=item.company,
        market_cap_cr=market_cap_cr,
        gross_asset_value_cr=base_assets,
        conservative_nav_cr=conservative_nav,
        base_nav_cr=base_nav,
        bull_nav_cr=bull_nav,
        discount_to_conservative_pct=discount_cons,
        discount_to_base_pct=discount_base,
        margin_of_safety_pct=margin,
        score=score,
        verdict=verdict,
        details={
            "holdings_count": len(item.holdings),
            "gross_holdings_cr": gross_holdings,
            "conservative_holdings_cr": conservative_holdings,
            "liabilities_cr": liabilities,
            "holding_company_discount_pct": item.holding_company_discount_pct,
        },
    )


def scan_hidden_value(candidates: Iterable[HiddenValueInput]) -> list[HiddenValueResult]:
    return sorted((analyze_hidden_value(x) for x in candidates), key=lambda x: (x.score, x.discount_to_conservative_pct), reverse=True)


def format_result(result: HiddenValueResult) -> str:
    return (f"PEREZ AI — HIDDEN VALUE\nCompany: {result.company}\n"
            f"Market Cap: ₹{result.market_cap_cr:,.2f} Cr\n"
            f"Conservative NAV: ₹{result.conservative_nav_cr:,.2f} Cr\n"
            f"Base NAV: ₹{result.base_nav_cr:,.2f} Cr\n"
            f"Bull NAV: ₹{result.bull_nav_cr:,.2f} Cr\n"
            f"Discount to NAV: {result.discount_to_conservative_pct:.1f}%\n"
            f"Margin of Safety: {result.margin_of_safety_pct:.1f}%\n"
            f"ELCID-TYPE SCORE: {result.score:.0f}/100\n"
            f"VERDICT: {result.verdict}")
