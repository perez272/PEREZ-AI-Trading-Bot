"""Read-only catalyst monitoring and paper-signal preparation.

This module never places orders. It only verifies catalyst provenance and
creates a deterministic monitoring record for downstream paper trading.
"""
from datetime import datetime, timezone
from src.catalyst_engine import verify_catalyst


def monitor_candidate(row, max_age_days=45):
    result = verify_catalyst(row, max_age_days=max_age_days)
    out = {
        "symbol": str(row.get("symbol", "")),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "catalyst_verified": bool(result.get("verified")),
        "catalyst_reason": result.get("reason"),
        "catalyst_types": result.get("types", []),
        "source_url": result.get("source_url", ""),
        "source_name": result.get("source_name", ""),
        "as_of_date": result.get("as_of_date", ""),
        "age_days": result.get("age_days"),
        "paper_trade_only": True,
        "trade_eligible": False,
        "orders_enabled": False,
        "status": "CATALYST_VERIFIED" if result.get("verified") else "CATALYST_UNVERIFIED",
    }
    return out


def monitor_candidates(rows, max_age_days=45):
    return [monitor_candidate(row, max_age_days=max_age_days) for row in rows]


if __name__ == "__main__":
    sample = {
        "symbol": "ELCIDINVESTMENTS",
        "corporate_action": True,
        "source_url": "https://www.moneycontrol.com/company-notices/elcidinvestments/notices/EIL/",
        "source_name": "BSE-sourced corporate-action announcements",
        "as_of_date": "2026-07-31",
    }
    print(monitor_candidate(sample))
