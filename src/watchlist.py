"""Default read-only Angel One quote watchlist.

This module contains only static instrument metadata. It never logs in or
calls the broker, making it safe for imports and tests.
"""

WATCHLIST = [
    ("NSE", "NIFTY", "99926000"),
    ("NSE", "BANKNIFTY", "99926009"),
    ("NSE", "RELIANCE", "2885"),
    ("NSE", "TCS", "11536"),
    ("NSE", "INFY", "1594"),
    ("NSE", "HDFCBANK", "1333"),
    ("NSE", "ICICIBANK", "4963"),
    ("NSE", "SBIN", "3045"),
    ("NSE", "AXISBANK", "5900"),
    ("NSE", "BHARTIARTL", "10604"),
]
