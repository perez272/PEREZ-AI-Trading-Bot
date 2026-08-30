"""Compatibility service for Tier-1 learning.

Tier-1 learning is now owned by the production market-data scan cycle. This
process intentionally performs NO market-data/API polling, preventing a second
observer from duplicating the production feed. It remains alive so existing
systemd supervision does not flap.
"""
from __future__ import annotations
import signal
import time

RUNNING = True

def _stop(*_args):
    global RUNNING
    RUNNING = False

def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("PEREZ AI Tier-1 Observer — SHARED PRODUCTION STREAM MODE")
    print("No independent market-data polling; learning is driven by main scan_market().")
    while RUNNING:
        time.sleep(60)

if __name__ == "__main__":
    main()
