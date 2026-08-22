"""Runtime configuration for PEREZ AI performance, coverage and risk gates."""

from datetime import time

# FAST SURGE MODE: keep paper-market observation responsive while preserving
# the existing fail-closed trading gates. 30s is deliberately conservative
# enough for Angel One API protection while materially faster than 60s.
FAST_SURGE_MODE = True
FAST_SURGE_SCAN_SECONDS = 30
RESCAN_DELAY_SECONDS = FAST_SURGE_SCAN_SECONDS if FAST_SURGE_MODE else 60
PER_SYMBOL_DELAY_SECONDS = 0
MAX_WORKERS = 4

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
MAX_DAILY_DRAWDOWN_PCT = 2.0
MAX_CONSECUTIVE_LOSSES = 2

# Preferred affordable-option universe. A cheap premium is a discovery filter,
# never a trade signal by itself.
OPTION_MAX_PREMIUM = 100.0
OPTIONS_MIN_SCORE = 60
MAX_SPREAD_PCT = 1.50
MAX_SLIPPAGE_PCT = 1.00

ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 45)
FORCED_EXIT_TIME = time(15, 10)
FRESHNESS_MAX_AGE_MINUTES = 5
HEALTH_STALE_AFTER_SECONDS = 120
