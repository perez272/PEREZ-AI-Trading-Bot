from __future__ import annotations


def _scan_message(heartbeat: dict) -> str:
    """Render read-only scan telemetry for Telegram.

    This function must never be used as an input to trading or risk decisions.
    """
    safety = "\n\n🛡️ TELEGRAM TELEMETRY IS READ-ONLY\nIt does not alter trading or risk decisions."
    if not heartbeat:
        return "🔎 SCAN TELEMETRY\nNo heartbeat scan telemetry persisted yet." + safety

    lines = ["🔎 PEREZ AI — DEEP SCAN TELEMETRY", "━━━━━━━━━━━━━━━━━━━━"]
    fields = (
        ("Status", heartbeat.get("status")),
        ("Capital", heartbeat.get("capital")),
        ("Candidates", heartbeat.get("candidates")),
        ("API attempts", heartbeat.get("market_data_api_attempts")),
        ("Live refreshes", heartbeat.get("market_data_live_refreshes")),
        ("Cache hits", heartbeat.get("market_data_cache_hits")),
        ("Fresh candles", heartbeat.get("market_data_fresh_candles")),
        ("Fresh → decision", heartbeat.get("market_data_fresh_to_decision")),
        ("Decision evaluations", heartbeat.get("decision_evaluations")),
        ("Provider failures", heartbeat.get("market_data_blocked_or_failed")),
        ("Stale/invalid", heartbeat.get("market_data_invalid_or_stale")),
    )
    for label, value in fields:
        if value is not None:
            lines.append(f"{label}: {value}")

    if len(lines) == 2:
        lines.append("No scan telemetry fields persisted yet.")

    return "\n".join(lines) + safety
