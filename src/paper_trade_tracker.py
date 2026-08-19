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


def _rows():
    """Read and normalize paper trades, including legacy rows.

    Older paper-trade files may predate ``trade_id`` and some of the current
    tracker fields. Normalize those rows on read so the live monitor can never
    fail repeatedly with KeyError and the canonical tracker remains usable.
    """
    _ensure_file()
    with TRADES_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)
        source_fields = set(reader.fieldnames or [])

    changed = source_fields != set(FIELDS)
    used_ids: set[str] = set()
    rows: list[dict] = []

    for index, raw in enumerate(raw_rows, start=1):
        row = {field: str(raw.get(field, "") or "") for field in FIELDS}

        if not row["trade_id"] or row["trade_id"] in used_ids:
            row["trade_id"] = f"PAPER-LEGACY-{index:06d}"
            changed = True
        used_ids.add(row["trade_id"])

        if not row["created_at"]:
            row["created_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
        if not row["quantity"]:
            row["quantity"] = "1"
            changed = True
        if not row["status"]:
            row["status"] = "OPEN"
            changed = True
        if not row["paper_trade_only"]:
            row["paper_trade_only"] = "True"
            changed = True
        if not row["orders_enabled"]:
            row["orders_enabled"] = "False"
            changed = True

        rows.append(row)

    if changed:
        _rewrite(rows)
    return rows


def open_trade(candidate: dict, quantity: int = 1) -> dict:
    if not candidate.get("paper_trade_only", True):
        raise ValueError("Only paper trades may be opened by this tracker")
    if candidate.get("orders_enabled") is not False:
        raise ValueError("orders_enabled must remain False")
    quantity = max(1, int(quantity))
    rows = _rows()
    trade_id = f"PAPER-{len(rows) + 1:06d}"
    existing_ids = {r["trade_id"] for r in rows}
    while trade_id in existing_ids:
        trade_id = f"PAPER-{len(rows) + 1:06d}-{len(existing_ids)}"

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
    found = next((row for row in rows if row["trade_id"] == trade_id), None)
    if found is None:
        raise KeyError(f"Unknown trade_id: {trade_id}")
    if found["status"] != "OPEN":
        raise ValueError("Trade is already closed")

    entry = float(found["entry"])
    stop = float(found["stop_loss"])
    qty = int(found["quantity"] or 1)
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
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRADES_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def performance() -> dict:
    rows = _rows()
    closed = [r for r in rows if r["status"] == "CLOSED"]
    pnls = [float(r["pnl"]) for r in closed if r["pnl"] not in ("", None)]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "total_trades": len(rows),
        "open_trades": sum(r["status"] == "OPEN" for r in rows),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "avg_r_multiple": round(sum(float(r["r_multiple"]) for r in closed if r["r_multiple"] not in ("", None)) / len(pnls), 3) if pnls else 0.0,
        "paper_trade_only": True,
        "orders_enabled": False,
    }


if __name__ == "__main__":
    print("PEREZ AI — PAPER PERFORMANCE")
    print(performance())
