import requests
from src.ai_memory import ai_suggestion, learning_summary, memory_status
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        print(f"Telegram alert failed: {error}")
        return False


def _learning_text(symbol):
    summary = learning_summary(symbol)
    stats = summary["symbol"] or summary["overall"]
    n = int(stats["n"])
    if n:
        win_rate = stats["wins"] / n * 100
        return f"Learned history: {n} trades | Win rate: {win_rate:.0f}% | P/L: Rs {stats['pnl']:.2f}"
    return "Learned history: collecting first paper-trade outcomes"


def send_entry_alert(trade):
    symbol = trade.get("symbol", "UNKNOWN")
    suggestion = ai_suggestion(symbol, trade.get("score", 0), trade.get("signal", ""))
    return send_alert(
        "🤖 PEREZ AI — PAPER TRADE\n\n"
        f"📌 {symbol} | {trade.get('signal', 'N/A')}\n"
        f"🎯 Contract: {trade.get('contract', 'N/A')}\n"
        f"💰 Entry: Rs {trade.get('entry', 0):.2f}\n"
        f"📦 Quantity: {trade.get('quantity', 0)}\n"
        f"🛑 Stop: Rs {trade.get('stop_loss', 0):.2f}\n"
        f"🎯 Target: Rs {trade.get('target', 0):.2f}\n"
        f"📊 AI score: {trade.get('score', 0)}/100\n"
        f"💡 {suggestion}\n\n"
        f"{_learning_text(symbol)}\n"
        f"{memory_status()}\n\n"
        "🔒 PAPER ONLY — no real order placed"
    )


def send_exit_alert(trade, result):
    label = {
        "TARGET": "TARGET HIT 🎯",
        "STOP_LOSS": "STOP LOSS HIT 🛑",
        "MARKET_CLOSE": "MARKET CLOSE EXIT ⏰",
    }.get(result.get("exit_reason"), "PAPER TRADE CLOSED")
    symbol = trade.get("symbol", "UNKNOWN")
    summary = learning_summary(symbol)
    stats = summary["symbol"] or summary["overall"]
    n = int(stats["n"])
    win_rate = (stats["wins"] / n * 100) if n else 0
    return send_alert(
        f"{label}\n\n"
        f"📌 {symbol} | {trade.get('contract', 'N/A')}\n"
        f"💰 Entry: Rs {result.get('entry', 0):.2f}\n"
        f"💵 Exit: Rs {result.get('current', 0):.2f}\n"
        f"📦 Quantity: {result.get('quantity', 0)}\n"
        f"📈 P/L: Rs {result.get('pnl', 0):.2f} ({result.get('pnl_percent', 0):.2f}%)\n"
        f"📝 Reason: {result.get('exit_reason', 'UNKNOWN')}\n\n"
        f"🧠 AI learning: {n} completed trades | {win_rate:.0f}% win rate\n"
        f"💡 {ai_suggestion(symbol)}\n\n"
        "🔒 PAPER ONLY — no real order placed"
    )
