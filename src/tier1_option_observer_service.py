"""Long-running observational worker for Tier-1 option-chain learning."""
from __future__ import annotations

import os
import signal
import time
from datetime import datetime

from src.session_clock import (
    IST,
    MARKET_CLOSE,
    MARKET_OPEN,
    is_weekday,
    next_weekday_0915,
)
from src.tier1_option_observer import observe_tier1_option_chains

RUNNING = True
# Keep the observer responsive enough to see fast moves while retaining the
# existing Upstox request pacing (one request/sec) inside the provider client.
INTERVAL_SECONDS = max(1, int(os.getenv("TIER1_OBSERVER_INTERVAL_SECONDS", "5")))
OUT_OF_SESSION_SLEEP_SECONDS = 30


def _stop(*_args):
    global RUNNING
    RUNNING = False


def _in_market_session(now: datetime) -> bool:
    """Return True only during the NSE market session, using canonical IST."""
    return is_weekday(now) and MARKET_OPEN <= now.time() < MARKET_CLOSE


def _sleep_until_market_session() -> None:
    """Sleep safely outside market hours without polling live option chains."""
    global RUNNING
    now = datetime.now(IST)
    if _in_market_session(now):
        return

    next_open = next_weekday_0915(now)
    wait_seconds = max(1, int((next_open - now).total_seconds()))
    print(
        f"[TIER1 OBSERVER] market session closed; no live polling. "
        f"Next session: {next_open.strftime('%Y-%m-%d %H:%M:%S IST')} "
        f"(sleep={wait_seconds}s)"
    )

    # Keep SIGTERM/SIGINT responsive rather than sleeping for the whole gap.
    remaining = wait_seconds
    while RUNNING and remaining > 0:
        step = min(OUT_OF_SESSION_SLEEP_SECONDS, remaining)
        time.sleep(step)
        remaining -= step


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("PEREZ AI Tier-1 Option Observer — PAPER/OBSERVATION ONLY")
    print("Universe: NIFTY | BANKNIFTY | FINNIFTY | MIDCPNIFTY | NIFTYNXT50")
    print("Explosive detector: 1m/3m/5m velocity + acceleration + volume + spread")

    while RUNNING:
        now = datetime.now(IST)
        if not _in_market_session(now):
            _sleep_until_market_session()
            continue

        try:
            events = observe_tier1_option_chains()
            early = [e for e in events if e.get("type") == "EARLY_EXPLOSIVE"]
            threshold = [e for e in events if e.get("type") == "THRESHOLD"]
            for event in early:
                print(
                    f"[EARLY EXPLOSIVE] {event['symbol']} {event['option_type']} "
                    f"score={event['score']:.1f} 1m={event['move_1m_pct']:.2f}% "
                    f"3m={event['move_3m_pct']:.2f}% 5m={event['move_5m_pct']:.2f}% "
                    f"accel={event['acceleration']:.2f} volx={event['volume_ratio']:.2f} "
                    f"spread={event['spread_pct']:.2f}% reasons={','.join(event['reasons'])}"
                )
            for event in threshold:
                print(
                    f"[TIER1 MOVE LEARNED] {event['symbol']} {event['option_type']} "
                    f"{event.get('contract','')} +{event['threshold']:.0f}% "
                    f"LTP={event['ltp']} baseline={event['baseline_ltp']} "
                    f"volume={event.get('volume')} OI={event.get('oi')} IV={event.get('iv')}"
                )
            if not events:
                print("[TIER1 OBSERVER] no early explosive signal or new move threshold")
        except Exception as exc:
            print(f"[TIER1 OBSERVER] cycle failed safely: {exc}")

        for _ in range(INTERVAL_SECONDS):
            if not RUNNING:
                break
            # Re-check the session boundary while waiting so the observer does
            # not begin another live cycle after 15:30 IST.
            if not _in_market_session(datetime.now(IST)):
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
