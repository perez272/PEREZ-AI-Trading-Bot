from datetime import datetime
from src.trading.logger import TradeLogger
from src.telegram_bot import send

class PaperTradeEngine:

    def __init__(self):
        self.position = None
        self.logger = TradeLogger()

    def open_trade(self, symbol, side, entry, qty=1):

        if self.position:
            return False

        self.position = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "qty": qty,
            "sl": entry * 0.98,
            "target": entry * 1.04,
            "trail": entry * 0.99,
            "opened": datetime.now(),
        }

        msg = (
            f"🟢 PAPER TRADE OPEN\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Entry: ₹{entry:.2f}\n"
            f"SL: ₹{self.position['sl']:.2f}\n"
            f"Target: ₹{self.position['target']:.2f}"
        )

        print(msg)
        send(msg)

        return True

    def update(self, price):

        if not self.position:
            return

        p = self.position

        if price > p["entry"] * 1.02:
            p["trail"] = max(p["trail"], price * 0.99)

        if price >= p["target"]:
            return self.close(price, "TARGET")

        if price <= p["trail"]:
            return self.close(price, "TRAILING SL")

        if price <= p["sl"]:
            return self.close(price, "STOP LOSS")

    def close(self, price, reason):

        p = self.position

        pnl = (price - p["entry"]) * p["qty"]

        self.logger.log_trade(
            p["symbol"],
            p["side"],
            p["entry"],
            price,
            p["qty"],
            pnl,
            reason,
        )

        msg = (
            f"🔴 PAPER TRADE CLOSED\n"
            f"Symbol: {p['symbol']}\n"
            f"Exit: ₹{price:.2f}\n"
            f"P/L: ₹{pnl:.2f}\n"
            f"Reason: {reason}"
        )

        print(msg)
        send(msg)

        self.position = None
        return pnl
