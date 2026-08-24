"""Runtime configuration for PEREZ AI performance, coverage and risk gates."""

from datetime import time

RESCAN_DELAY_SECONDS = 60
PER_SYMBOL_DELAY_SECONDS = 0
MAX_WORKERS = 4

# HARD SCANNER POLICY: PEREZ AI scans index F&O only.
# No individual equity/security is allowed into the market scanner universe.
# NSE currently offers derivatives on these six major indices.
TIER1_INDEX_SYMBOLS = (
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYFPI",
)

# Stable Angel One index tokens. NIFTYNXT50 and NIFTYFPI are resolved from the
# local instrument master so token changes cannot silently break the scanner.
SYMBOLS = {
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "FINNIFTY": ("NSE", "99926037"),
    "MIDCPNIFTY": ("NSE", "99926074"),
}

# Backward-compatible setting only. scanner_universe enforces the Tier-1
# allowlist and never expands into equity F&O securities.
SCAN_BATCH_SIZE = len(TIER1_INDEX_SYMBOLS)

MINIMUM_SCORE = 65
MAX_TECHNICAL_BYPASS_SCORE = 80
MAX_TRADES_PER_DAY = 3
MAX_DAILY_DRAWDOWN_PCT = 2.0
MAX_CONSECUTIVE_LOSSES = 2

OPTION_MAX_PREMIUM = 150.0
OPTIONS_MIN_SCORE = 60
MAX_SPREAD_PCT = 1.50
MAX_SLIPPAGE_PCT = 1.00

INDEX_MOMENTUM_ENABLED = True
INDEX_MOMENTUM_MIN_SCORE = 72

ENTRY_START = time(9, 20)
LAST_ENTRY = time(15, 0)
FORCED_EXIT_TIME = time(15, 10)
FRESHNESS_MAX_AGE_MINUTES = 5
HEALTH_STALE_AFTER_SECONDS = 120
