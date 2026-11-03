"""Run one observational Upstox option-chain snapshot; no loop or order path."""
from __future__ import annotations

import argparse
import json

from src.alternative_market_data import get_upstox_client
from src.short_covering_snapshot_collector import ShortCoveringSnapshotCollector


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--expiry", default=None, help="YYYY-MM-DD; omit for nearest available expiry")
    parser.add_argument(
        "--db",
        default="data/short_covering_observations.sqlite3",
        help="SQLite observation database path",
    )
    args = parser.parse_args()
    client = get_upstox_client()
    if not client.available():
        parser.error("Upstox is unavailable; check UPSTOX_ENABLED and UPSTOX_ACCESS_TOKEN")
    collector = ShortCoveringSnapshotCollector(client, args.db)
    try:
        result = collector.capture(args.symbol, expiry=args.expiry)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
