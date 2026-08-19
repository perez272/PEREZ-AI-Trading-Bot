"""Convert verified discovery results into paper-trade candidates only.

Safety invariant: this module never imports or calls a broker/order API and
never marks a candidate as live-trade eligible.
"""
from datetime import datetime, timezone


def build_paper_candidate(result, entry_price, risk_pct=0.02, reward_multiple=3.0):
    """Build a deterministic paper setup from an admitted/watchlist result.

    The candidate risks ``risk_pct`` of the supplied paper capital per trade
    and targets ``reward_multiple`` times the per-share risk. Position sizing
    is deliberately omitted here because capital/account constraints belong to
    the paper portfolio layer.
    """
    if not isinstance(result, dict):
        raise TypeError("result must be a dict")
    price = float(entry_price)
    if price <= 0:
        raise ValueError("entry_price must be positive")
    if not 0 < float(risk_pct) < 1:
        raise ValueError("risk_pct must be between 0 and 1")
    if float(reward_multiple) <= 0:
        raise ValueError("reward_multiple must be positive")

    risk_per_share = round(price * float(risk_pct), 2)
    stop = round(price - risk_per_share, 2)
    target = round(price + risk_per_share * float(reward_multiple), 2)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": str(result.get("symbol") or "").upper(),
        "score": result.get("score"),
        "nav_discount_pct": result.get("nav_discount_pct"),
        "asset_ratio": result.get("asset_ratio"),
        "catalyst_verified": result.get("catalyst_verified") is True,
        "catalyst_types": result.get("catalyst_types", []),
        "entry": price,
        "stop_loss": stop,
        "target": target,
        "risk_per_share": risk_per_share,
        "reward_multiple": float(reward_multiple),
        "paper_trade_only": True,
        "trade_eligible": False,
        "orders_enabled": False,
        "status": "PAPER_CANDIDATE",
    }


def build_from_discovery(admitted, watchlist, prices, risk_pct=0.02, reward_multiple=3.0):
    """Create paper candidates for verified discovery outputs with known prices."""
    candidates = []
    for result in list(admitted or []) + list(watchlist or []):
        symbol = str(result.get("symbol") or "").upper()
        if symbol not in prices:
            continue
        candidate = build_paper_candidate(
            result,
            prices[symbol],
            risk_pct=risk_pct,
            reward_multiple=reward_multiple,
        )
        candidates.append(candidate)
    return sorted(candidates, key=lambda x: float(x.get("score") or 0), reverse=True)


if __name__ == "__main__":
    sample = {
        "symbol": "ELCIDINVESTMENTS",
        "score": 56,
        "nav_discount_pct": 78.75,
        "asset_ratio": 4.92,
        "catalyst_verified": True,
        "catalyst_types": ["corporate_action"],
    }
    print(build_paper_candidate(sample, 108905))
