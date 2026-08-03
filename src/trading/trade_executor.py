from src.trading.paper_engine import PaperTradeEngine

engine = PaperTradeEngine()

def execute_signal(signal):
    if signal is None:
        return

    if signal["signal"] not in ("BUY CE", "BUY PE"):
        return

    side = "BUY"

    engine.open_trade(
        symbol=signal["symbol"],
        side=side,
        entry=signal["close"],
        qty=1
    )
