"""Paper-only monitor connected to the canonical paper trade tracker.

The monitor uses the existing AngelClient for read-only LTP polling. It never
calls an order endpoint and always remains paper-only. The long-running mode
is designed for systemd: transient broker/API failures are retried by the
AngelClient and unexpected monitor failures are isolated so the service can
continue operating.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.paper_trade_tracker import close_trade, _rows


INSTRUMENTS_FILE = Path("data/instruments.json")
DEFAULT_INTERVAL_SECONDS = 10.0
IDLE_INTERVAL_SECONDS = 30.0


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
    """Check every currently-open paper trade once."""
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

    No order API is used. ``once=False`` keeps polling until interrupted.
    """
    while True:
        rows = [r for r in _rows() if r.get("status") == "OPEN"]
        if not rows:
            return []

        for row in rows:
            instrument = instrument_lookup.get(row["symbol"])
            if not instrument:
                print(f"[MONITOR] Instrument not found: {row['symbol']}", flush=True)
                continue
            exchange, token = instrument
            response = angel_client.get_ltp(exchange, row["symbol"], str(token))
            if not response:
                print(f"[MONITOR] No LTP response: {row['symbol']}", flush=True)
                continue
            data = response.get("data") if isinstance(response, dict) else None
            ltp = data.get("ltp") if isinstance(data, dict) else None
            if ltp is not None:
                print(f"[MONITOR] {row['symbol']} LTP={float(ltp):.2f}", flush=True)
                monitor_trade(row, float(ltp))

        if once:
            return rows
        time.sleep(max(1.0, float(interval_seconds)))


def _load_instrument_lookup(path: Path = INSTRUMENTS_FILE) -> dict[str, tuple[str, str]]:
    """Build a symbol -> (exchange, token) lookup from Angel's instrument dump."""
    if not path.exists():
        raise FileNotFoundError(f"Missing instrument file: {path}")
    with path.open(encoding="utf-8") as f:
        instruments = json.load(f)

    lookup: dict[str, tuple[str, str]] = {}
    for item in instruments:
        if not isinstance(item, dict) or item.get("exch_seg") != "NSE":
            continue
        token = item.get("token")
        raw_symbol = str(item.get("symbol") or "").upper()
        name = str(item.get("name") or "").upper()
        if not token:
            continue
        clean = raw_symbol.removesuffix("-EQ")
        if clean:
            lookup.setdefault(clean, (item["exch_seg"], str(token)))
        if name:
            lookup.setdefault(name, (item["exch_seg"], str(token)))
    return lookup


def run_forever(interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
    """Run the read-only LTP monitor forever, recovering from transient errors."""
    from src.broker.angel_client import AngelClient
    from src.broker.session_manager import SessionManager
    from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET

    if not all((API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)):
        raise RuntimeError("Angel One credentials are missing from environment")

    manager = SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET)
    smartapi = manager.get_client()
    client = AngelClient(smartapi, session_manager=manager)
    lookup = _load_instrument_lookup()

    print("PEREZ AI — PAPER TRADE MONITOR SERVICE", flush=True)
    print({
        "connected_tracker": "src.paper_trade_tracker",
        "automatic_ltp_monitor": True,
        "poll_interval_seconds": interval_seconds,
        "paper_trade_only": True,
        "orders_enabled": False,
    }, flush=True)

    while True:
        try:
            open_rows = [r for r in _rows() if r.get("status") == "OPEN"]
            if open_rows:
                monitor_with_angel_client(
                    client,
                    lookup,
                    once=True,
                    interval_seconds=interval_seconds,
                )
            else:
                print("[MONITOR] No open paper trades; waiting.", flush=True)
            time.sleep(interval_seconds if open_rows else IDLE_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("[MONITOR] Stopped by operator.", flush=True)
            return
        except Exception as exc:
            print(f"[MONITOR] Recoverable error: {exc!r}; retrying in 15s", flush=True)
            time.sleep(15)


def main() -> None:
    if os.getenv("PEREZ_PAPER_MONITOR_ONCE", "0") == "1":
        print("PEREZ AI — PAPER TRADE MONITOR")
        print({
            "connected_tracker": "src.paper_trade_tracker",
            "close_conditions": ["STOP_LOSS", "TARGET"],
            "automatic_ltp_monitor": True,
            "paper_trade_only": True,
            "orders_enabled": False,
        })
        return
    run_forever(float(os.getenv("PEREZ_PAPER_MONITOR_INTERVAL", DEFAULT_INTERVAL_SECONDS)))


if __name__ == "__main__":
    main()
