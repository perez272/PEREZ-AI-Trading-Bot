from pathlib import Path
import csv

from src.equity_value_ranker import EquityEvidence, rank

EVIDENCE = Path("data/fundamental_source_evidence.csv")

def main():
    if not EVIDENCE.exists():
        raise SystemExit("Missing fundamental source evidence")

    rows = list(csv.DictReader(EVIDENCE.open(encoding="utf-8")))
    admitted = []
    rejected = []

    for r in rows:
        if (
            r.get("fundamental_verified") != "TRUE"
            or r.get("nav_verified") != "TRUE"
            or r.get("assets_verified") != "TRUE"
            or r.get("catalyst_verified") != "TRUE"
        ):
            rejected.append((r.get("symbol",""), "MISSING_VERIFIED_EVIDENCE"))
            continue

        try:
            result = rank(EquityEvidence(
                symbol=r["symbol"],
                market_cap_cr=float(r.get("market_cap_cr", 0)),
                nav_cr=float(r.get("nav_cr", 0)),
                listed_assets_cr=float(r.get("listed_assets_cr", 0)),
                catalyst_verified=True,
            ))
            if result["eligible"]:
                admitted.append(result)
            else:
                rejected.append((r["symbol"], result["reason"]))
        except Exception as exc:
            rejected.append((r.get("symbol",""), f"INVALID_INPUT:{type(exc).__name__}"))

    print("=" * 76)
    print("PEREZ AI — EQUITY VALUE-EVENT DISCOVERY")
    print("=" * 76)
    print("MODE              : READ ONLY")
    print("PAPER TRADING     : ENABLED")
    print("LIVE ORDERS       : DISABLED")
    print(f"RESEARCH RECORDS  : {len(rows)}")
    print(f"ADMITTED >=80     : {len(admitted)}")
    print(f"REJECTED          : {len(rejected)}")
    print("-" * 76)

    for x in admitted[:20]:
        print(f"ADMITTED {x['symbol']} | {x['score']}/100 | {x['reason']}")

    print("-" * 76)
    print("UNVERIFIED FUNDAMENTALS : REJECTED")
    print("MISSING NAV/assets      : REJECTED")
    print("MISSING CATALYST       : REJECTED")
    print("LIVE ORDERS             : FALSE")
    print("=" * 76)

if __name__ == "__main__":
    main()
