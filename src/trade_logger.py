import csv
from pathlib import Path

FIELDS = [
    "closed_at", "underlying", "signal", "contract", "exchange",
    "entry", "exit", "original_quantity", "exit_quantity", "remaining_quantity",
    "lots", "investment", "realized_pnl", "unrealized_pnl", "pnl",
    "pnl_percent", "exit_reason",
]


def _ensure_schema(output: Path):
    if not output.exists() or output.stat().st_size == 0:
        return
    with output.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        old_fields = reader.fieldnames or []
        if old_fields == FIELDS:
            return
        rows = list(reader)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def log_closed_trade(trade, result, path="data/trades.csv"):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(output)
    record = {
        "closed_at": result["time"],
        "underlying": trade.get("symbol", ""),
        "signal": trade.get("signal", ""),
        "contract": trade["contract"],
        "exchange": trade.get("exchange", ""),
        "entry": result["entry"],
        "exit": result["current"],
        "original_quantity": result.get("original_quantity", trade.get("quantity", "")),
        "exit_quantity": result.get("quantity", ""),
        "remaining_quantity": result.get("remaining_quantity", 0),
        "lots": trade.get("lots", ""),
        "investment": trade.get("investment", ""),
        "realized_pnl": result.get("realized_pnl", 0.0),
        "unrealized_pnl": result.get("unrealized_pnl", 0.0),
        "pnl": result["pnl"],
        "pnl_percent": result["pnl_percent"],
        "exit_reason": result["exit_reason"],
    }
    with output.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
        if output.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(record)
    return record
