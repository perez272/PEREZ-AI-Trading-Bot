from pathlib import Path
import csv, re, time, requests
from bs4 import BeautifulSoup
from urllib.parse import quote

QUEUE = Path("data/fundamental_research_queue.csv")
OUT = Path("data/fundamental_research_results.csv")
LIMIT = 250

FIELDS = [
    "symbol","exchange","token","company_name",
    "research_status","primary_source_found",
    "source_url","annual_report_found",
    "fundamental_data_verified","admit_to_gate"
]

def clean(v):
    return re.sub(r"[^A-Za-z0-9 .&()_-]", "", str(v or "")).strip()

def search_symbol(symbol, company):
    q = quote(f'"{company or symbol}" annual report financial results investments')
    url = f"https://www.google.com/search?q={q}"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if r.status_code != 200:
            return None, False
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(" ", strip=True).lower()
            if "http" in href and (
                "annual" in text or
                "financial" in text or
                "results" in text or
                "investor" in text
            ):
                links.append(href)
        return (links[0] if links else None), bool(links)
    except Exception:
        return None, False

def main():
    print("=" * 76)
    print("PEREZ AI — FUNDAMENTAL RESEARCH ENGINE")
    print("=" * 76)
    print("MODE              : READ ONLY")
    print("PAPER TRADING     : ENABLED")
    print("LIVE ORDERS       : DISABLED")
    print("FUNDAMENTALS      : VERIFIED DATA ONLY")
    print("=" * 76)

    if not QUEUE.exists():
        print("ERROR: research queue does not exist:", QUEUE)
        return 1

    rows = list(csv.DictReader(QUEUE.open(newline="", encoding="utf-8")))
    rows = rows[:LIMIT]

    OUT.parent.mkdir(parents=True, exist_ok=True)

    results = []
    found = 0

    for i, row in enumerate(rows, 1):
        symbol = clean(row.get("symbol"))
        company = clean(
            row.get("company_name")
            or row.get("name")
            or row.get("tradingsymbol")
            or symbol
        )

        source, has_source = search_symbol(symbol, company)

        if has_source:
            found += 1
            status = "SOURCE_DISCOVERED_NEEDS_VERIFICATION"
            annual = "POSSIBLE"
        else:
            status = "NO_PRIMARY_SOURCE_DISCOVERED"
            annual = "NO"

        results.append({
            "symbol": symbol,
            "exchange": clean(row.get("exchange")),
            "token": clean(row.get("token")),
            "company_name": company,
            "research_status": status,
            "primary_source_found": str(has_source).upper(),
            "source_url": source or "",
            "annual_report_found": annual,
            "fundamental_data_verified": "FALSE",
            "admit_to_gate": "FALSE",
        })

        if i % 25 == 0:
            print(f"Research checked: {i}/{len(rows)}")
        time.sleep(0.25)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)

    print()
    print("=" * 76)
    print("RESEARCH RESULT")
    print("=" * 76)
    print(f"Queue records processed       : {len(rows)}")
    print(f"Potential primary sources     : {found}")
    print(f"Verified fundamental records  : 0")
    print(f"Admitted to high-conviction   : 0")
    print(f"Output                        : {OUT}")
    print("-" * 76)
    print("IMPORTANT:")
    print("Source discovery is NOT fundamental verification.")
    print("NAV/assets/catalyst values are NOT fabricated.")
    print("Unverified candidates CANNOT reach the gate.")
    print("LIVE ORDERS : FALSE")
    print("PAPER TRADE : PRESERVED")
    print("=" * 76)
    print("STATUS: RESEARCH SOURCES DISCOVERED — VERIFICATION LAYER REQUIRED")
    print("=" * 76)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
