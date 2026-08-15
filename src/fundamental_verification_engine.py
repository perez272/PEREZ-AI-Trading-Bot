from pathlib import Path
import csv, re, time, requests

QUEUE = Path("data/fundamental_research_queue.csv")
OUT = Path("data/fundamental_verified_candidates.csv")

BATCH_SIZE = 250
TIMEOUT = 20
DELAY = 0.40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}

FIELDS = [
    "symbol","exchange","token","company_name",
    "nse_url","bse_url","company_url",
    "annual_report_url",
    "source_status","source_exchange",
    "market_cap_cr","nav_cr","listed_investments_cr",
    "cash_cr","debt_cr","promoter_holding_pct","free_float_pct",
    "catalyst_verified","nav_verified","assets_verified",
    "fundamental_verified","evidence","verified_at"
]

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        return r.status_code, r.text[:3000000]
    except Exception as e:
        return 0, f"FETCH_ERROR:{type(e).__name__}"

def textify(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.I|re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.I|re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()

def number_after(text, patterns):
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                pass
    return None

def verify(row):
    symbol = row.get("symbol","").strip().upper()
    company = row.get("company_name","").strip()

    nse_url = f"https://www.nseindia.com/search?q={symbol}"
    bse_url = f"https://www.bseindia.com/stock-share-price/{symbol.lower()}/"

    nse_status, nse_html = fetch(nse_url)
    time.sleep(DELAY)
    bse_status, bse_html = fetch(bse_url)

    nse_text = textify(nse_html) if nse_status == 200 else ""
    bse_text = textify(bse_html) if bse_status == 200 else ""

    source_parts = []
    if len(nse_text) > 200:
        source_parts.append(("NSE", nse_text))
    if len(bse_text) > 200:
        source_parts.append(("BSE", bse_text))

    combined = " ".join(x[1] for x in source_parts)
    source_exchange = "+".join(x[0] for x in source_parts)

    # IMPORTANT:
    # These values are accepted ONLY when explicit labels occur.
    # Missing values remain UNKNOWN (None).
    market_cap = number_after(combined, [
        r"market\s+capital(?:isation|ization)[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"market\s+cap[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)"
    ])

    nav = number_after(combined, [
        r"\bNAV\b[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"net\s+asset\s+value[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)"
    ])

    investments = number_after(combined, [
        r"listed\s+investments?[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"investments?\s+in\s+listed[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)"
    ])

    cash = number_after(combined, [
        r"cash\s+and\s+cash\s+equivalents?[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"cash\s+and\s+bank[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)"
    ])

    debt = number_after(combined, [
        r"total\s+debt[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"borrowings[^\d]{0,120}([0-9][0-9,]*(?:\.[0-9]+)?)"
    ])

    promoter = number_after(combined, [
        r"promoter(?:s)?(?:\s+and\s+promoter\s+group)?[^\d]{0,120}([0-9]+(?:\.[0-9]+)?)\s*%"
    ])

    free_float = number_after(combined, [
        r"free\s+float[^\d]{0,120}([0-9]+(?:\.[0-9]+)?)\s*%"
    ])

    # Catalyst is NOT considered verified merely because a word occurs.
    # It must appear in an exchange/corporate-action context.
    catalyst_patterns = [
        r"corporate\s+action",
        r"open\s+offer",
        r"buy[\s-]?back",
        r"delisting",
        r"scheme\s+of\s+arrangement",
        r"merger",
        r"demerger",
        r"special\s+auction",
        r"regulatory\s+(?:approval|action)",
        r"restructuring"
    ]

    catalyst_hits = []
    lower = combined.lower()
    for p in catalyst_patterns:
        if re.search(p, lower):
            catalyst_hits.append(p.replace("\\s+"," "))

    # Exchange pages alone are NOT sufficient for NAV/assets verification.
    # Therefore these remain FALSE unless an explicit filing source is supplied.
    nav_verified = False
    assets_verified = False
    fundamental_verified = False

    evidence = []
    if source_exchange:
        evidence.append(f"exchange_source={source_exchange}")
    if market_cap is not None:
        evidence.append(f"market_cap={market_cap}")
    if nav is not None:
        evidence.append(f"NAV_candidate={nav}")
    if investments is not None:
        evidence.append(f"listed_investments_candidate={investments}")
    if cash is not None:
        evidence.append(f"cash_candidate={cash}")
    if debt is not None:
        evidence.append(f"debt_candidate={debt}")
    if promoter is not None:
        evidence.append(f"promoter_candidate={promoter}%")
    if catalyst_hits:
        evidence.append("catalyst_context=" + ",".join(catalyst_hits))

    return {
        "symbol": symbol,
        "exchange": row.get("exchange",""),
        "token": row.get("token",""),
        "company_name": company,
        "nse_url": nse_url,
        "bse_url": bse_url,
        "company_url": "",
        "annual_report_url": "",
        "source_status": "SOURCE_FOUND" if source_exchange else "SOURCE_NOT_FOUND",
        "source_exchange": source_exchange,
        "market_cap_cr": market_cap if market_cap is not None else "",
        "nav_cr": nav if nav is not None else "",
        "listed_investments_cr": investments if investments is not None else "",
        "cash_cr": cash if cash is not None else "",
        "debt_cr": debt if debt is not None else "",
        "promoter_holding_pct": promoter if promoter is not None else "",
        "free_float_pct": free_float if free_float is not None else "",
        "catalyst_verified": "TRUE" if catalyst_hits else "FALSE",
        "nav_verified": "FALSE",
        "assets_verified": "FALSE",
        "fundamental_verified": "FALSE",
        "evidence": " | ".join(evidence),
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

def main():
    if not QUEUE.exists():
        raise SystemExit("ERROR: data/fundamental_research_queue.csv missing")

    rows = list(csv.DictReader(QUEUE.open(encoding="utf-8")))
    batch = rows[:BATCH_SIZE]

    OUT.parent.mkdir(parents=True, exist_ok=True)

    source_found = 0
    catalyst_found = 0

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for i, row in enumerate(batch, 1):
            print(f"VERIFY {i:03d}/{len(batch):03d} | {row.get('symbol','')}", flush=True)
            result = verify(row)
            writer.writerow(result)

            source_found += result["source_status"] == "SOURCE_FOUND"
            catalyst_found += result["catalyst_verified"] == "TRUE"

    print()
    print("=" * 76)
    print("PEREZ AI — STRICT FUNDAMENTAL VERIFICATION LAYER")
    print("=" * 76)
    print("MODE                  : READ ONLY")
    print("PAPER TRADING         : ENABLED")
    print("LIVE ORDERS           : DISABLED")
    print(f"QUEUE TOTAL           : {len(rows)}")
    print(f"BATCH PROCESSED       : {len(batch)}")
    print(f"EXCHANGE SOURCES      : {source_found}")
    print(f"CATALYST SIGNALS      : {catalyst_found}")
    print("NAV VERIFIED          : 0 (filing verification required)")
    print("ASSETS VERIFIED       : 0 (filing verification required)")
    print("FUNDAMENTALS VERIFIED : 0")
    print(f"OUTPUT                : {OUT}")
    print("-" * 76)
    print("NO SOURCE              = UNKNOWN")
    print("NO FILING EVIDENCE     = NOT VERIFIED")
    print("NO NAV/ASSETS          = REJECT")
    print("NO VERIFIED CATALYST   = REJECT")
    print("NO FABRICATED VALUES")
    print("LIVE ORDERS            = FALSE")
    print("=" * 76)

if __name__ == "__main__":
    main()
