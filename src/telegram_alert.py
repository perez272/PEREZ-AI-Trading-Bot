import requests
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


def send_entry_alert(trade):
    return send_alert(
        "PAPER TRADE OPENED\n\n"
        f"Underlying: {trade['symbol']}\n"
        f"Signal: {trade['signal']}\n"
        f"Contract: {trade['contract']}\n"
        f"Entry: Rs {trade['entry']:.2f}\n"
        f"Quantity: {trade['quantity']}\n"
        f"Stop loss: Rs {trade['stop_loss']:.2f}\n"
        f"Target: Rs {trade['target']:.2f}"
    )


def send_exit_alert(trade, result):
    label = {
        "TARGET": "TARGET HIT",
        "STOP_LOSS": "STOP LOSS HIT",
        "MARKET_CLOSE": "MARKET CLOSE EXIT",
    }.get(result["exit_reason"], "PAPER TRADE CLOSED")

    return send_alert(
        f"{label}\n\n"
        f"Underlying: {trade['symbol']}\n"
        f"Contract: {trade['contract']}\n"
        f"Entry: Rs {result['entry']:.2f}\n"
        f"Exit: Rs {result['current']:.2f}\n"
        f"Quantity: {result['quantity']}\n"
        f"P/L: Rs {result['pnl']:.2f} ({result['pnl_percent']:.2f}%)\n"
        f"Reason: {result['exit_reason']}"
    )
