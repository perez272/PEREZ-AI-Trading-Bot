from dataclasses import dataclass

@dataclass
class EquityEvidence:
    symbol: str
    market_cap_cr: float
    nav_cr: float
    listed_assets_cr: float
    catalyst_verified: bool
    balance_sheet_quality: float = 0.0
    promoter_quality: float = 0.0
    liquidity_quality: float = 0.0
    corporate_action_verified: bool = False
    technical_confirmation: float = 0.0

def rank(e):
    if e.market_cap_cr <= 0 or e.nav_cr <= 0 or e.listed_assets_cr <= 0:
        return {"score": 0, "eligible": False, "reason": "MISSING_NAV_OR_ASSETS"}

    nav_discount = max(0.0, 1.0 - e.market_cap_cr / e.nav_cr)
    asset_ratio = e.listed_assets_cr / e.market_cap_cr

    nav_pts = min(25.0, nav_discount * 25.0 / 0.90)
    asset_pts = min(20.0, asset_ratio / 20.0 * 20.0)
    catalyst_pts = 20.0 if e.catalyst_verified else 0.0
    balance_pts = min(10.0, max(0.0, e.balance_sheet_quality))
    promoter_pts = min(5.0, max(0.0, e.promoter_quality))
    liquidity_pts = min(5.0, max(0.0, e.liquidity_quality))
    action_pts = 10.0 if e.corporate_action_verified else 0.0
    technical_pts = min(5.0, max(0.0, e.technical_confirmation))

    score = round(
        nav_pts + asset_pts + catalyst_pts + balance_pts +
        promoter_pts + liquidity_pts + action_pts + technical_pts
    )

    eligible = (
        score >= 80
        and nav_discount >= 0.50
        and asset_ratio >= 3.0
        and e.catalyst_verified
    )

    return {
        "symbol": e.symbol,
        "score": score,
        "nav_discount_pct": round(nav_discount * 100, 2),
        "asset_ratio": round(asset_ratio, 2),
        "eligible": eligible,
        "reason": "HIGH_CONVICTION" if eligible else "STRICT_GATE_REJECT",
    }

if __name__ == "__main__":
    print("PEREZ AI — EQUITY VALUE-EVENT RANKER")
    print("100-POINT FUNDAMENTAL/EVENT MODEL")
    print("STRICT GATE >=80 | NAV/assets REQUIRED | CATALYST REQUIRED")
