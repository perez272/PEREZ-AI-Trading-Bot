"""Monitor open paper candidates and close them on stop/target.

Safety: this module is paper-only and never calls broker order APIs.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import csv

STATE = Path("data/paper_trades.csv")

@dataclass
class PaperTrade:
    symbol: str
    entry: float
    stop_loss: float
    target: float
    status: str = "OPEN"
    exit_price: float = 0.0
    exit_reason: str = ""
    closed_at: str = ""


def check_trade(trade: PaperTrade, ltp: float) -> PaperTrade:
    if trade.status != "OPEN":
        return trade
    if ltp <= trade.stop_loss:
        trade.status = "CLOSED"
        trade.exit_price = trade.stop_loss
        trade.exit_reason = "STOP_LOSS"
    elif ltp >= trade.target:
        trade.status = "CLOSED"
        trade.exit_price = trade.target
        trade.exit_reason = "TARGET"
    if trade.status == "CLOSED":
        trade.closed_at = datetime.now(timezone.utc).isoformat()
    return trade


def pnl(trade: PaperTrade) -> float:
    if trade.status != "CLOSED":
        return 0.0
    return trade.exit_price - trade.entry


def save_trade(trade: PaperTrade) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    exists = STATE.exists()
    fields = list(asdict(trade).keys())
    with STATE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(asdict(trade))


def main() -> None:
    # Safe demonstration using the existing paper candidate levels.
    trade = PaperTrade(
        symbol="ELCIDINVESTMENTS",
        entry=108905.0,
        stop_loss=106726.9,
        target=115439.3,
    )
    print("PEREZ AI — PAPER TRADE MONITOR")
    print({"symbol": trade.symbol, "status": trade.status,
           "entry": trade.entry, "stop_loss": trade.stop_loss,
           "target": trade.target, "paper_trade_only": True,
           "orders_enabled": False})

if __name__ == "__main__":
    main()
