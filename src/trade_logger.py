import csv
from pathlib import Path


FIELDS = [
    "closed_at", "underlying", "signal", "contract", "exchange",
    "entry", "exit", "quantity", "lots", "investment",
    "pnl", "pnl_percent", "exit_reason",
]


def log_closed_trade(trade, result, path="data/trades.csv"):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "closed_at": result["time"],
        "underlying": trade.get("symbol", ""),
        "signal": trade.get("signal", ""),
        "contract": trade["contract"],
        "exchange": trade.get("exchange", ""),
        "entry": result["entry"],
        "exit": result["current"],
        "quantity": result["quantity"],
        "lots": trade.get("lots", ""),
        "investment": trade.get("investment", ""),
        "pnl": result["pnl"],
        "pnl_percent": result["pnl_percent"],
        "exit_reason": result["exit_reason"],
    }

    exists = output.exists()
    with output.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(record)

    return record
