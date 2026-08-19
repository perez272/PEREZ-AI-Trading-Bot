"""PEREZ AI — read-only paper trade tracker with Telegram notifications.

Tracks simulated candidates/exits only. It never calls a broker and never
changes the live-order safety state.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from src.telegram_alert import send_alert

TRADES_FILE = Path("data/paper_trades.csv")
FIELDS = [
    "trade_id", "created_at", "symbol", "entry", "stop_loss", "target",
    "quantity", "status", "exit", "pnl", "r_multiple", "reason", "closed_at",
    "paper_trade_only", "orders_enabled",
]


def _ensure_file():
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TRADES_FILE.exists():
        with TRADES_FILE.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def _normalize_rows(rows: list[dict]) -> list[dict]:
    """Normalize legacy CSV rows so monitoring never fails on missing keys."""
    changed = False
    for index, row in enumerate(rows, start=1):
        defaults = {
            "trade_id": f"PAPER-{index:06d}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "symbol": "",
            "entry": "0",
            "stop_loss": "0",
            "target": "0",
            "quantity": "1",
            "status": "OPEN",
            "exit": "",
            "pnl": "",
            "r_multiple": "",
            "reason": "",
            "closed_at": "",
            "paper_trade_only": "True",
            "orders_enabled": "False",
        }
        for field in FIELDS:
            if field not in row or row[field] in (None, "") and field in {"trade_id", "quantity", "status", "paper_trade_only", "orders_enabled"}:
                row[field] = defaults[field]
                changed = True
        if row.get("trade_id") == "":
            row["trade_id"] = defaults["trade_id"]
            changed = True
        if row.get("status") == "":
            row["status"] = "OPEN"
            changed = True
    if changed:
        _rewrite(rows)
    return rows


def _rows():
    _ensure_file()
    with TRADES_FILE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return _normalize_rows(rows)


def open_trade(candidate: dict, quantity: int = 1) -> dict:
    if not candidate.get("paper_trade_only", True):
        raise ValueError("Only paper trades may be opened by this tracker")
    if candidate.get("orders_enabled") is not False:
        raise ValueError("orders_enabled must remain False")
    quantity = max(1, int(quantity))
    rows = _rows()
    trade_id = f"PAPER-{len(rows) + 1:06d}"
    row = {
        "trade_id": trade_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": candidate["symbol"],
        "entry": candidate["entry"],
        "stop_loss": candidate["stop_loss"],
        "target": candidate["target"],
        "quantity": quantity,
        "status": "OPEN",
        "exit": "",
        "pnl": "",
        "r_multiple": "",
        "reason": "",
        "closed_at": "",
        "paper_trade_only": True,
        "orders_enabled": False,
    }
    with TRADES_FILE.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)

    send_alert(
        "🟢 PEREZ AI — PAPER TRADE OPENED\n\n"
        f"Trade: {trade_id}\n"
        f"Symbol: {row['symbol']}\n"
        f"Entry: ₹{float(row['entry']):,.2f}\n"
        f"Stop: ₹{float(row['stop_loss']):,.2f}\n"
        f"Target: ₹{float(row['target']):,.2f}\n"
        f"Quantity: {quantity}\n\n"
        "PAPER ONLY — ORDERS DISABLED"
    )
    return row


def close_trade(trade_id: str, exit_price: float, reason: str = "") -> dict:
    rows = _rows()
    found = next((row for row in rows if row.get("trade_id") == trade_id), None)
    if found is None:
        raise KeyError(f"Unknown trade_id: {trade_id}")
    if found.get("status") != "OPEN":
        raise ValueError("Trade is already closed")

    entry = float(found["entry"])
    stop = float(found["stop_loss"])
    qty = max(1, int(found["quantity"]))
    exit_price = float(exit_price)
    risk = abs(entry - stop) * qty
    pnl = (exit_price - entry) * qty
    r_multiple = round(pnl / risk, 3) if risk else 0.0
    result = {
        "status": "CLOSED",
        "exit": exit_price,
        "pnl": round(pnl, 2),
        "r_multiple": r_multiple,
        "reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    found.update(result)
    _rewrite(rows)

    outcome = "🏆 WIN" if pnl > 0 else "🔴 LOSS" if pnl < 0 else "⚪ BREAKEVEN"
    send_alert(
        f"{outcome} — PEREZ AI PAPER TRADE\n\n"
        f"Trade: {trade_id}\n"
        f"Symbol: {found['symbol']}\n"
        f"Entry: ₹{entry:,.2f}\n"
        f"Exit: ₹{exit_price:,.2f}\n"
        f"P/L: ₹{pnl:,.2f}\n"
        f"R: {r_multiple:.3f}\n"
        f"Reason: {reason or 'CLOSED'}\n\n"
        "PAPER ONLY — ORDERS DISABLED"
    )
    return found


def _rewrite(rows):
    with TRADES_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def performance() -> dict:
    rows = _rows()
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    pnls = [float(r["pnl"]) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "total_trades": len(rows),
        "open_trades": sum(r.get("status") == "OPEN" for r in rows),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "avg_r_multiple": round(sum(float(r["r_multiple"]) for r in closed) / len(closed), 3) if closed else 0.0,
        "paper_trade_only": True,
        "orders_enabled": False,
    }


if __name__ == "__main__":
    print("PEREZ AI — PAPER PERFORMANCE")
    print(performance())
