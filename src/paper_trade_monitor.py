"""Paper-only monitor connected to the canonical paper trade tracker.

The monitor can use an injected LTP provider (recommended for tests) or an
AngelClient. It never calls an order endpoint and always remains paper-only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from src.paper_trade_tracker import close_trade, _rows


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


def monitor_open_trades(ltp_provider: Callable[[dict], float]) -> list[dict]:
    """Check every currently-open paper trade once.

    ``ltp_provider(row)`` must return the current LTP for that row. This keeps
    broker access outside the tracker and makes the monitor easy to test.
    """
    results = []
    for row in _rows():
        if row.get("status") != "OPEN":
            continue
        ltp = ltp_provider(row)
        monitor_trade(row, float(ltp))
        results.append({"trade_id": row["trade_id"], "symbol": row["symbol"], "ltp": float(ltp)})
    return results


def monitor_with_angel_client(angel_client, instrument_lookup: dict, once: bool = True, interval_seconds: float = 5.0):
    """Monitor open paper trades using the existing AngelClient.get_ltp().

    ``instrument_lookup`` maps symbols to ``(exchange, token)``. No order API
    is used. ``once=True`` performs one scan; ``False`` keeps polling until
    interrupted.
    """
    while True:
        rows = [r for r in _rows() if r.get("status") == "OPEN"]
        if not rows:
            return []

        for row in rows:
            instrument = instrument_lookup.get(row["symbol"])
            if not instrument:
                continue
            exchange, token = instrument
            response = angel_client.get_ltp(exchange, row["symbol"], str(token))
            if not response:
                continue
            data = response.get("data") if isinstance(response, dict) else None
            ltp = data.get("ltp") if isinstance(data, dict) else None
            if ltp is not None:
                monitor_trade(row, float(ltp))

        if once:
            return rows
        time.sleep(max(1.0, float(interval_seconds)))


def main() -> None:
    print("PEREZ AI — PAPER TRADE MONITOR")
    print({
        "connected_tracker": "src.paper_trade_tracker",
        "close_conditions": ["STOP_LOSS", "TARGET"],
        "automatic_ltp_monitor": True,
        "paper_trade_only": True,
        "orders_enabled": False,
    })


if __name__ == "__main__":
    main()
