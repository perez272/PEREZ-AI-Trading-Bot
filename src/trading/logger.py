import csv
import os
from datetime import datetime

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "paper_trades.csv")

os.makedirs(LOG_DIR, exist_ok=True)

class TradeLogger:

    def __init__(self):
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Time",
                    "Symbol",
                    "Side",
                    "Entry",
                    "Exit",
                    "Qty",
                    "PnL",
                    "Reason"
                ])

    def log_trade(self, symbol, side, entry, exit_price, qty, pnl, reason):
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol,
                side,
                round(entry, 2),
                round(exit_price, 2),
                qty,
                round(pnl, 2),
                reason,
            ])

        print("✅ Trade logged.")
