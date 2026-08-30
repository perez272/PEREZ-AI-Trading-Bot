"""Long-running observational worker for Tier-1 option-chain learning."""
from __future__ import annotations

import signal
import time

from src.tier1_option_observer import observe_tier1_option_chains, get_tier1_option_observer

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
    print("Explosive detector: 1m/3m/5m velocity + acceleration + volume + spread")
    print("Learning milestones: 5 | 10 | 50 | 100 | 150% (milestones, never automatic exits)")
    while RUNNING:
        try:
            events = observe_tier1_option_chains()
            early = [e for e in events if e.get("type") == "EARLY_EXPLOSIVE"]
            threshold = [e for e in events if e.get("type") == "THRESHOLD"]
            for event in early:
                print(f"[EARLY EXPLOSIVE] {event['symbol']} {event['option_type']} score={event['score']:.1f} 1m={event['move_1m_pct']:.2f}% 3m={event['move_3m_pct']:.2f}% 5m={event['move_5m_pct']:.2f}%")
            for event in threshold:
                print(f"[TIER1 MOVE LEARNED] {event['symbol']} {event['option_type']} {event.get('contract','')} +{event['threshold']:.0f}% LTP={event['ltp']} baseline={event['baseline_ltp']} source={event.get('data_source','unknown')} exit_policy={event.get('exit_policy','milestone_only')}")
            sensor = get_tier1_option_observer().stats().get("data_sensor", {})
            if not sensor.get("healthy", True):
                print(f"[DATA SENSOR] FAILURE count={sensor.get('failure_count')} failures={sensor.get('failures', [])[-3:]}")
            if not events:
                print("[TIER1 OBSERVER] no early explosive signal or new move threshold")
        except Exception as exc:
            print(f"[DATA SENSOR] PIPELINE_CYCLE_FAILURE: {exc}")
        for _ in range(INTERVAL_SECONDS):
            if not RUNNING:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
