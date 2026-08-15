from pathlib import Path
import csv

QUEUE = Path("data/fundamental_research_queue.csv")
OUT = Path("data/fundamental_source_evidence.csv")

FIELDS = [
    "symbol","exchange","token","company_name",
    "nse_source","bse_source","company_source",
    "annual_report_source","fundamental_verified",
    "nav_verified","assets_verified","catalyst_verified",
    "admit_to_equity_ranker"
]

def main():
    if not QUEUE.exists():
        raise SystemExit("Missing data/fundamental_research_queue.csv")

    rows = list(csv.DictReader(QUEUE.open(encoding="utf-8")))
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()

        for r in rows:
            symbol = r.get("symbol", "").strip()
            exchange = r.get("exchange", "").strip()
            token = r.get("token", "").strip()
            name = r.get("company_name", "").strip()

            # Discovery only. No filing is treated as verified automatically.
            w.writerow({
                "symbol": symbol,
                "exchange": exchange,
                "token": token,
                "company_name": name,
                "nse_source": f"https://www.nseindia.com/search?q={symbol}",
                "bse_source": f"https://www.bseindia.com/stock-share-price/{symbol}/",
                "company_source": "",
                "annual_report_source": "",
                "fundamental_verified": "FALSE",
                "nav_verified": "FALSE",
                "assets_verified": "FALSE",
                "catalyst_verified": "FALSE",
                "admit_to_equity_ranker": "FALSE",
            })

    print("=" * 76)
    print("PEREZ AI — NSE/BSE FUNDAMENTAL SOURCE LAYER")
    print("=" * 76)
    print(f"Instrument records queued : {len(rows)}")
    print(f"Evidence file              : {OUT}")
    print("NSE source                 : ENABLED")
    print("BSE source                 : ENABLED")
    print("Company source             : SUPPORTED")
    print("NAV verification           : REQUIRED")
    print("Asset verification         : REQUIRED")
    print("Catalyst verification      : REQUIRED")
    print("Fabricated fundamentals    : FALSE")
    print("Admitted candidates        : 0")
    print("LIVE ORDERS                : FALSE")
    print("PAPER TRADING              : TRUE")
    print("=" * 76)

if __name__ == "__main__":
    main()
