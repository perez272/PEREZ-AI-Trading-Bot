"""Paper-only monitor connected to the canonical paper trade tracker."""
from __future__ import annotations

from dataclasses import dataclass

from src.paper_trade_tracker import close_trade


@dataclass
class PaperTrade:
    trade_id: str
    symbol: str
    entry: float
    stop_loss: float
    target: float
    status: str = "OPEN"


def check_trade(trade: PaperTrade, ltp: float) -> PaperTrade:
    """Close an open paper trade at its stop or target via the tracker."""
    if trade.status != "OPEN":
        return trade

    exit_price = None
    reason = ""
    if ltp <= trade.stop_loss:
        exit_price, reason = trade.stop_loss, "STOP_LOSS"
    elif ltp >= trade.target:
        exit_price, reason = trade.target, "TARGET"

    if exit_price is not None:
        result = close_trade(trade.trade_id, exit_price, reason)
        trade.status = result["status"]

    return trade


def monitor_trade(trade_row: dict, ltp: float) -> dict:
    """Monitor one tracker row and close it when a trigger is reached."""
    trade = PaperTrade(
        trade_id=trade_row["trade_id"],
        symbol=trade_row["symbol"],
        entry=float(trade_row["entry"]),
        stop_loss=float(trade_row["stop_loss"]),
        target=float(trade_row["target"]),
        status=trade_row["status"],
    )
    check_trade(trade, float(ltp))
    return trade_row


def main() -> None:
    print("PEREZ AI — PAPER TRADE MONITOR")
    print({
        "connected_tracker": "src.paper_trade_tracker",
        "close_conditions": ["STOP_LOSS", "TARGET"],
        "paper_trade_only": True,
        "orders_enabled": False,
    })


if __name__ == "__main__":
    main()
