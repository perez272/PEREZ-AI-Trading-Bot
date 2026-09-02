import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.upgrade_config import ENTRY_START, LAST_ENTRY, FORCED_EXIT_TIME, MAX_CONSECUTIVE_LOSSES, MAX_DAILY_DRAWDOWN_PCT
from src.trading_risk_manager import TradingRiskManager

IST = ZoneInfo("Asia/Kolkata")

# Persistent timed circuit breaker / trailing-risk state.
TRADING_RISK_MANAGER = TradingRiskManager()


def now_ist():
    return datetime.now(IST)


def is_entry_window(current=None):
    current = current or now_ist()
    return current.weekday() < 5 and ENTRY_START <= current.time() <= LAST_ENTRY


def should_force_exit(current=None):
    current = current or now_ist()
    return current.weekday() < 5 and current.time() >= FORCED_EXIT_TIME


def daily_summary(path="data/trades.csv", current=None):
    current = current or now_ist()
    today = current.strftime("%Y-%m-%d")
    output = Path(path)
    summary = {"closed_trades": 0, "pnl": 0.0, "consecutive_losses": 0, "worst_loss": 0.0}
    if not output.exists():
        return summary

    rows = []
    with output.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("closed_at", "").startswith(today):
                try:
                    row["_pnl"] = float(row.get("pnl", 0) or 0)
                except (TypeError, ValueError):
                    row["_pnl"] = 0.0
                rows.append(row)

    summary["closed_trades"] = len(rows)
    summary["pnl"] = round(sum(row["_pnl"] for row in rows), 2)
    summary["worst_loss"] = round(min((row["_pnl"] for row in rows), default=0.0), 2)
    for row in reversed(rows):
        if row["_pnl"] < 0:
            summary["consecutive_losses"] += 1
        else:
            break
    return summary


def can_open_new_trade(max_trades=3, max_daily_loss=None, capital=0):
    """Apply risk gates using the current available capital.

    max_daily_loss is retained for backwards compatibility, but when omitted
    the authoritative daily loss limit is 2% of the live capital.
    """
    if not is_entry_window():
        return False, "Outside entry window: 09:30-14:45 IST", daily_summary()

    summary = daily_summary()
    if summary["closed_trades"] >= max_trades:
        return False, f"Daily trade limit reached ({max_trades})", summary

    dynamic_limit = abs(float(capital)) * MAX_DAILY_DRAWDOWN_PCT / 100.0
    daily_loss_limit = dynamic_limit if max_daily_loss is None else min(abs(float(max_daily_loss)), dynamic_limit)
    if daily_loss_limit <= 0:
        return False, "No valid available capital for risk checks", summary

    if summary["pnl"] <= -daily_loss_limit:
        return False, f"Daily loss limit reached (2% of capital = Rs {daily_loss_limit:.2f})", summary
    if capital > 0 and summary["pnl"] <= -dynamic_limit:
        return False, f"Daily drawdown limit reached ({MAX_DAILY_DRAWDOWN_PCT:.1f}%)", summary
    if TRADING_RISK_MANAGER.is_circuit_breaker_active():
        remaining = TRADING_RISK_MANAGER.circuit_breaker_remaining()
        minutes = max(1, int((remaining + 59) // 60))
        return False, f"Timed circuit breaker active ({minutes} min remaining)", summary
    return True, "Risk checks passed", summary
