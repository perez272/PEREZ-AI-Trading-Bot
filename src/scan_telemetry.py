def _money(value):
    return f"₹{value:,.2f}"


def _share_report(shares, limit=10):
    lines = ["📊 TOP SHARES"]
    ok = [x for x in shares if x.get("status") == "OK"]
    rejected = [x for x in shares if x.get("status") != "OK"]
    lines.append(f"Scanned: {len(shares)} | Fresh: {len(ok)} | Rejected: {len(rejected)}")
    for item in ok[:limit]:
        lines.append(
            f"• {item['symbol']} | {item['score']}/100 | {_money(item['close'])} | "
            f"RSI {item['rsi']:.1f} | {item['signal']} | {item['trend']} | age {item['age_minutes']:.2f}m"
        )
    if rejected:
        counts = {}
        for item in rejected:
            status = item.get("status", "ERROR")
            counts[status] = counts.get(status, 0) + 1
        lines.append("Rejected summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return lines


def _options_report(options, limit=10):
    lines = ["", "📈 TOP OPTIONS"]
    if not options:
        lines.append("No option candidates returned.")
        return lines
    ranked = sorted(options, key=lambda x: x.get("options_score", 0), reverse=True)
    for item in ranked[:limit]:
        lines.append(
            f"• {item.get('symbol')} {item.get('option_type','')} | "
            f"score {item.get('options_score', 0)}/100 | "
            f"LTP {_money(float(item.get('ltp', 0) or 0))} | "
            f"candidate={bool(item.get('paper_trade_candidate'))}"
        )
    return lines


def _elcid_report(elcid):
    lines = ["", "🏦 ELCID — SEPARATE READ-ONLY STAGE"]
    lines.append(f"LTP: {_money(elcid['ltp'])} | Orders enabled: NO")
    lines.append(
        f"Reported NAV/share: {_money(elcid['reported_nav_per_share'])} | "
        f"Discount: {elcid['market_discount_to_reported_nav_pct']:.2f}%"
    )
    lines.append("Portfolio categories:")
    for item in elcid["categories"]:
        lines.append(f"• {item['name']}: ₹{item['value_cr']:,.2f} Cr")
    lines.append(
        "Scenarios: "
        + " | ".join(
            f"{name} {_money(data['nav_per_share'])}"
            for name, data in elcid["scenarios"].items()
        )
    )
    return lines


def build_scan_report(shares, options, elcid, scan_number):
    lines = [
        f"🤖 PEREZ AI — SCAN #{scan_number}",
        "━━━━━━━━━━━━━━━━━━━━",
        "PAPER MODE ONLY — NO REAL ORDERS",
    ]
    lines.extend(_share_report(shares))
    lines.extend(_options_report(options))
    lines.extend(_elcid_report(elcid))
    lines.append("")
    lines.append("🔒 Execution path unchanged: scanners are read-only; trade creation remains behind existing risk/options gates.")
    return "\n".join(lines)
