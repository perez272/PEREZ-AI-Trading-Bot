"""Long-running observational worker for Tier-1 option-chain learning."""
from __future__ import annotations

import signal
import time

from src.tier1_option_observer import observe_tier1_option_chains
from src.tier1_pipeline_bridge import process_new_observations

RUNNING = True
INTERVAL_SECONDS = 60


def _stop(*_args):
    global RUNNING
    RUNNING = False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("PEREZ AI Tier-1 Option Observer — PAPER/OBSERVATION ONLY")
    print("Pipeline: DETECTED -> CAPTURED -> ANALYZED -> STORED -> LEARNED")
    print("Universe: NIFTY | BANKNIFTY | FINNIFTY | MIDCPNIFTY | NIFTYNXT50 | NIFTYFPI")
    while RUNNING:
        try:
            events = observe_tier1_option_chains()
            pipeline = process_new_observations()
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
            print(
                "[TIER1 PIPELINE] "
                f"captured={pipeline['captured']} processed={pipeline['processed']} "
                f"analyzed={pipeline['analyzed']} early={pipeline['early_signals']} "
                f"surges={pipeline['surge_events']} lessons={pipeline['lessons']}"
            )
            if not events and pipeline["processed"] == 0:
                print("[TIER1 OBSERVER] no new signal or unprocessed observation")
        except Exception as exc:
            print(f"[TIER1 OBSERVER] cycle failed safely: {exc}")
        for _ in range(INTERVAL_SECONDS):
            if not RUNNING:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
