"""Runtime configuration for PEREZ AI performance, coverage and risk gates."""

from datetime import time

RESCAN_DELAY_SECONDS = 60
PER_SYMBOL_DELAY_SECONDS = 0
MAX_WORKERS = 4

# Coverage controls. The Angel One master can contain 100k+ derivative rows;
# scanning every contract every minute is neither necessary nor API-safe.
# We therefore build the universe from NSE equities with NFO contracts and
# cap the active underlying scan to a controlled, deterministic size.
MAX_SCAN_SYMBOLS = 150
UNIVERSE_REQUIRE_FNO = True

# Kept as a fallback for environments where the local instrument master is
# unavailable. The runtime scanner prefers the dynamic optionable universe.
SYMBOLS = {
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "FINNIFTY": ("NSE", "99926037"),
    "RELIANCE": ("NSE", "2885"),
    "TCS": ("NSE", "11536"),
    "INFY": ("NSE", "1594"),
    "HDFCBANK": ("NSE", "1333"),
    "ICICIBANK": ("NSE", "4963"),
    "SBIN": ("NSE", "3045"),
    "AXISBANK": ("NSE", "5900"),
}

MINIMUM_SCORE = 65
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 300.0
MAX_DAILY_DRAWDOWN_PCT = 2.0
MAX_CONSECUTIVE_LOSSES = 2

OPTIONS_MIN_SCORE = 60
MAX_SPREAD_PCT = 1.50
MAX_SLIPPAGE_PCT = 1.00

ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 45)
FORCED_EXIT_TIME = time(15, 10)
FRESHNESS_MAX_AGE_MINUTES = 5
HEALTH_STALE_AFTER_SECONDS = 120
