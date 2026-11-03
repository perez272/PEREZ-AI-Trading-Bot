"""Bounded command-line runner for the standalone short-covering collector.

Example:
  venv/bin/python scripts/collect_short_covering_snapshots.py --symbols NIFTY --polls 7 --interval-seconds 60

This is research/observation only. It does not start or modify perez-ai.service.
"""
from __future__ import annotations

import argparse
import time

from src.short_covering_snapshot_collector import (
    DEFAULT_DB,
    DEFAULT_SYMBOLS,
    ShortCoveringSnapshotCollector,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect paper-only Upstox option-chain snapshots")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--polls", type=int, default=7)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    if not 2 <= args.polls <= 100:
        parser.error("--polls must be between 2 and 100")
    if not 20 <= args.interval_seconds <= 300:
        parser.error("--interval-seconds must be between 20 and 300")
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    if not symbols:
        parser.error("--symbols must contain at least one symbol")

    from src.alternative_market_data import UpstoxMarketData

    client = UpstoxMarketData()
    if not client.available():
        print("ERROR: Upstox is not configured or unavailable.")
        return 2

    collector = ShortCoveringSnapshotCollector(
        client,
        args.db,
        min_interval_seconds=15,
        max_interval_seconds=max(180, args.interval_seconds * 2),
    )
    expiries: dict[str, str] = {}

    for poll in range(args.polls):
        for symbol in symbols:
            try:
                result = collector.capture(symbol, expiry=expiries.get(symbol))
                if symbol not in expiries and result["analysis"]:
                    expiries[symbol] = result["analysis"][0]["expiry"]
                print(
                    f"{symbol} poll {poll + 1}/{args.polls}: "
                    f"saved={result['contracts_saved']} "
                    f"evaluated={result['contracts_evaluated']} "
                    f"signals={len(result['signals'])}"
                )
                for signal in result["signals"]:
                    print(
                        "EVIDENCE",
                        symbol, signal["expiry"], signal["strike"], signal["option_type"],
                        f"OI={signal['oi_change_pct']:.2f}%",
                        f"price={signal['price_change_pct']:.2f}%",
                        f"interval_volume={signal['interval_volume']:.0f}",
                        f"volume_ratio={signal['volume_ratio']:.2f}x",
                    )
            except Exception as exc:
                print(f"{symbol} poll {poll + 1}: ERROR {type(exc).__name__}: {exc}")
        if poll + 1 < args.polls:
            time.sleep(args.interval_seconds)

    print(f"Finished. Database: {args.db}. OBSERVATION ONLY; no strategy/order integration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
