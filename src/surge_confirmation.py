"""Data-driven surge confirmation. Shadow/backtest safe; does not alter risk limits."""
from __future__ import annotations

def confirm(event):
    f = event or {}
    m1 = float(f.get("move_1m_pct", 0) or 0)
    m3 = float(f.get("move_3m_pct", 0) or 0)
    m5 = float(f.get("move_5m_pct", 0) or 0)
    accel = float(f.get("acceleration", 0) or 0)
    spread = float(f.get("spread_pct", 999) or 999)
    volume = float(f.get("volume_ratio", 0) or 0)
    score = float(f.get("score", 0) or 0)

    reasons = []
    points = 0

    # Evidence-based continuation zone.
    if m3 >= 3.0:
        points += 1
        reasons.append("M3_CONTINUATION")
    if m5 >= 3.0:
        points += 1
        reasons.append("M5_CONTINUATION")

    # Avoid chasing extreme 1m spikes.
    if 2.0 <= m1 <= 8.5:
        points += 1
        reasons.append("CONTROLLED_M1")

    # Controlled acceleration: high acceleration was more common in FALSE_SURGE.
    if 2.5 <= accel <= 13.5:
        points += 1
        reasons.append("CONTROLLED_ACCEL")

    # Strongest historical separator.
    if spread <= 1.27:
        points += 2
        reasons.append("TIGHT_SPREAD")
    elif spread <= 2.84:
        points += 1
        reasons.append("ACCEPTABLE_SPREAD")

    if volume >= 1.03:
        points += 1
        reasons.append("VOLUME_SUPPORT")

    if score >= 65:
        points += 1
        reasons.append("SCORE_SUPPORT")

    # Require continuation and execution quality.
    confirmed = (
        points >= 6
        and m3 >= 3.0
        and m5 >= 3.0
        and spread <= 2.84
    )

    return {
        "confirmed": confirmed,
        "points": points,
        "reasons": reasons,
        "metrics": {
            "m1": m1, "m3": m3, "m5": m5,
            "acceleration": accel, "spread": spread,
            "volume": volume, "score": score,
        },
    }
