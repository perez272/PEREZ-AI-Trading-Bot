"""Long-running observational worker for Tier-1 option-chain learning."""
from __future__ import annotations

import signal
import time

from src.tier1_option_observer import observe_tier1_option_chains

RUNNING = True
INTERVAL_SECONDS = 60


def _stop(*_args):
    global RUNNING
    RUNNING = False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("PEREZ AI Tier-1 Option Observer — PAPER/OBSERVATION ONLY")
    print("Universe: NIFTY | BANKNIFTY | FINNIFTY | MIDCPNIFTY | NIFTYNXT50 | NIFTYFPI")
    while RUNNING:
        try:
            events = observe_tier1_option_chains()
            if events:
                for event in events:
                    print(
                        f"[TIER1 MOVE LEARNED] {event['symbol']} {event['option_type']} "
                        f"{event.get('contract','')} +{event['threshold']:.0f}% "
                        f"LTP={event['ltp']} baseline={event['baseline_ltp']} "
                        f"volume={event.get('volume')} OI={event.get('oi')} IV={event.get('iv')}"
                    )
            else:
                print("[TIER1 OBSERVER] no new 5/10/15/20% threshold crossing")
        except Exception as exc:
            print(f"[TIER1 OBSERVER] cycle failed safely: {exc}")
        for _ in range(INTERVAL_SECONDS):
            if not RUNNING:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
