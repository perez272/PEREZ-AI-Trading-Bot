"""PEREZ AI catalyst verification layer.

Catalysts are never inferred from valuation discounts. A catalyst is eligible
only when an explicit catalyst flag is present AND a source reference and
as-of date are present. This module is read-only and never enables orders.
"""
from datetime import date

CATALYST_FIELDS = (
    "corporate_action",
    "regulatory_catalyst",
    "special_auction",
    "restructuring_event",
)


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def verify_catalyst(row, max_age_days=45):
    """Return a conservative catalyst verification result.

    A flag without provenance is deliberately rejected. No valuation metric,
    price movement, NAV discount, or classification can create a catalyst.
    """
    active = [f for f in CATALYST_FIELDS if _truthy(row.get(f))]
    source = str(row.get("source_url") or "").strip()
    source_name = str(row.get("source_name") or "").strip()
    as_of = str(row.get("as_of_date") or "").strip()

    if not active:
        return {"verified": False, "reason": "MISSING_CATALYST", "types": []}
    if not source or not source_name or not as_of:
        return {
            "verified": False,
            "reason": "CATALYST_MISSING_PROVENANCE",
            "types": active,
        }
    try:
        age = (date.today() - date.fromisoformat(as_of)).days
    except ValueError:
        return {
            "verified": False,
            "reason": "CATALYST_INVALID_AS_OF_DATE",
            "types": active,
        }
    if age < 0:
        return {
            "verified": False,
            "reason": "CATALYST_FUTURE_DATED",
            "types": active,
        }
    if age > max_age_days:
        return {
            "verified": False,
            "reason": "CATALYST_STALE",
            "types": active,
            "age_days": age,
        }
    return {
        "verified": True,
        "reason": "CATALYST_VERIFIED",
        "types": active,
        "age_days": age,
        "source_url": source,
        "source_name": source_name,
        "as_of_date": as_of,
    }
