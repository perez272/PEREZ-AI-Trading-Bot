import csv
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
ENTRY_START = time(9, 30)
LAST_ENTRY = time(14, 45)
MARKET_CLOSE = time(15, 30)
FORCED_EXIT_TIME = MARKET_CLOSE
RUNTIME_START = time(9, 15)
RUNTIME_STOP = time(15, 31)


def now_ist():
    return datetime.now(IST)


def is_entry_window(current=None):
    current = current or now_ist()
    return (
        current.weekday() < 5
        and ENTRY_START <= current.time() <= LAST_ENTRY
    )


def is_runtime_window(current=None):
    """True while the bot is expected to be running on a trading day."""
    current = current or now_ist()
    return (
        current.weekday() < 5
        and RUNTIME_START <= current.time() < RUNTIME_STOP
    )


def should_force_exit(current=None):
    current = current or now_ist()
    return current.weekday() < 5 and current.time() >= FORCED_EXIT_TIME


def daily_summary(path="data/trades.csv", current=None):
    current = current or now_ist()
    today = current.strftime("%Y-%m-%d")
    output = Path(path)

    summary = {"closed_trades": 0, "pnl": 0.0}
    if not output.exists():
        return summary

    with output.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("closed_at", "").startswith(today):
                summary["closed_trades"] += 1
                summary["pnl"] += float(row.get("pnl", 0) or 0)

    summary["pnl"] = round(summary["pnl"], 2)
    return summary


def can_open_new_trade(max_trades=3, max_daily_loss=300.0):
    if not is_entry_window():
        return False, "Outside entry window: 09:30-14:45 IST", daily_summary()

    summary = daily_summary()

    if summary["closed_trades"] >= max_trades:
        return False, f"Daily trade limit reached ({max_trades})", summary

    if summary["pnl"] <= -abs(max_daily_loss):
        return False, f"Daily loss limit reached (Rs {max_daily_loss:.2f})", summary

    return True, "Risk checks passed", summary
