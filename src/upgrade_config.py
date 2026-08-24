"""Runtime configuration for PEREZ AI performance, coverage and risk gates."""

from datetime import time

RESCAN_DELAY_SECONDS = 60
PER_SYMBOL_DELAY_SECONDS = 0
MAX_WORKERS = 4

SYMBOLS = {
    "SENSEX": ("BSE", "99919000"),
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "FINNIFTY": ("NSE", "99926037"),
    "MIDCPNIFTY": ("NSE", "99926074"),
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

# Dedicated index-momentum strategy gate. It is stricter than the base scanner
# and remains paper-only until separately proven in real sessions.
INDEX_MOMENTUM_ENABLED = True
INDEX_MOMENTUM_MIN_SCORE = 72

ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 45)
FORCED_EXIT_TIME = time(15, 10)
FRESHNESS_MAX_AGE_MINUTES = 5
HEALTH_STALE_AFTER_SECONDS = 120
