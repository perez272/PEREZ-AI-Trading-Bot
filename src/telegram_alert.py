import requests
from src.ai_memory import ai_suggestion, learning_summary, learned_confidence, memory_status
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


def _learning_text(symbol, regime=None):
    summary = learning_summary(symbol, regime)
    stats = summary["scope"]
    n = int(stats["n"])
    if n:
        win_rate = stats["wins"] / n * 100
        return f"🧠 Learned history: {n} trades | Win rate: {win_rate:.0f}% | P/L: Rs {stats['pnl']:.2f}"
    return "🧠 Learned history: collecting first paper-trade outcomes"


def _surge_text(symbol=None, contract=None):
    try:
        from src.options_surge_engine import surge_summary
        from src.expiry_learning_engine import expiry_learning_summary
        events = surge_summary(20)
        if symbol:
            events = [e for e in events if e.get("symbol") == symbol or (contract and e.get("contract") == contract)]
        lines = []
        for e in events[:4]:
            lines.append(
                f"⚡ +{e['change_pct']:.1f}% | {e['window_minutes']}m | {e['contract']} | "
                f"₹{e['start_ltp']:.2f}→₹{e['end_ltp']:.2f} | {e.get('expiry_bucket','UNKNOWN')}"
            )
        profile = expiry_learning_summary()
        if lines:
            return "\n⚡ OPTIONS SURGE LEARNING\n" + "\n".join(lines) + "\n" + f"Expiry profiles: {profile or 'collecting'}\n"
        return "\n⚡ OPTIONS SURGE LEARNING\nNo +5/+10/+15% surge event recorded for this contract yet.\n"
    except Exception as exc:
        return f"\n⚠️ Surge-learning status unavailable: {exc}\n"


def _analysis_text(trade):
    symbol = trade.get("symbol", "UNKNOWN")
    regime = trade.get("regime") or "unknown"
    confidence = learned_confidence(symbol, regime)
    return (
        "\n📊 EASY AI SUMMARY\n"
        f"AI score: {float(trade.get('score', 0) or 0):.0f}/100\n"
        f"Options score: {float(trade.get('options_score', 0) or 0):.0f}/100\n"
        f"Learned confidence: {confidence:.0f}%\n"
        f"Market regime: {regime}\n"
        f"💡 Suggestion: {ai_suggestion(symbol, trade.get('score', 0), trade.get('signal', ''), regime)}\n"
        + _surge_text(symbol, trade.get("contract"))
        + _learning_text(symbol, regime) + "\n"
    )


def send_entry_alert(trade):
    return send_alert(
        "🤖 PEREZ AI — PAPER TRADE\n\n"
        f"📌 {trade.get('symbol', 'UNKNOWN')} | {trade.get('signal', 'N/A')}\n"
        f"🎯 Contract: {trade.get('contract', 'N/A')}\n"
        f"💰 Entry: Rs {trade.get('entry', 0):.2f}\n"
        f"📦 Quantity: {trade.get('quantity', 0)}\n"
        f"🛑 Stop: Rs {trade.get('stop_loss', 0):.2f}\n"
        f"🎯 Target: Rs {trade.get('target', 0):.2f}\n"
        + _analysis_text(trade)
        + "\n🔒 PAPER ONLY — no real order placed"
    )


def send_options_surge_alert(event, learning=None):
    """Human-readable surge alert. A surge is an event, never a BUY command."""
    event = event or {}
    learning = learning or {}
    suggestion = learning.get("suggestion", "Do not chase the move; wait for confirmation.")
    return send_alert(
        "⚡ PEREZ AI — OPTIONS SURGE DETECTED\n\n"
        f"📌 {event.get('symbol', 'UNKNOWN')} {event.get('option_type', '')}\n"
        f"🎯 {event.get('contract', 'N/A')}\n"
        f"⏱ Window: {event.get('window_minutes', 0)} min\n"
        f"📈 Move: +{float(event.get('change_pct', 0)):.2f}%\n"
        f"💰 Premium: Rs {float(event.get('start_ltp', 0)):.2f} → Rs {float(event.get('end_ltp', 0)):.2f}\n"
        f"📅 Expiry profile: {event.get('expiry_bucket', 'UNKNOWN')}\n"
        f"🧠 Samples: {learning.get('same_window_samples', 0)} same-window events\n"
        f"💡 AI suggestion: {suggestion}\n"
        "🔎 Event only — NOT an automatic trade signal.\n"
        "🔒 PAPER ONLY — no real order placed"
    )


def send_exit_alert(trade, result):
    label = {
        "TARGET": "TARGET HIT 🎯",
        "STOP_LOSS": "STOP LOSS HIT 🛑",
        "MARKET_CLOSE": "MARKET CLOSE EXIT ⏰",
    }.get(result.get("exit_reason"), "PAPER TRADE CLOSED")
    symbol = trade.get("symbol", "UNKNOWN")
    regime = trade.get("regime") or "unknown"
    summary = learning_summary(symbol, regime)
    stats = summary["scope"]
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
        f"🧠 Learning: {n} completed trades | {win_rate:.0f}% win rate\n"
        f"💡 Suggestion: {ai_suggestion(symbol, trade.get('score', 0), trade.get('signal', ''), regime)}\n"
        + _surge_text(symbol, trade.get("contract"))
        + f"{memory_status()}\n\n"
        "🔒 PAPER ONLY — no real order placed"
    )
