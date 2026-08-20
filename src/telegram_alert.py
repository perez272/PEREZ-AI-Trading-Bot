import os
import time
import threading

import requests
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_LOCK = threading.Lock()
_LAST_SENT = 0.0
_MIN_INTERVAL = max(0.5, float(os.getenv("TELEGRAM_MIN_INTERVAL_SECONDS", "1.0")))
_TIMEOUT = max(3, int(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "8")))


def send_alert(message, *, force=False):
    global _LAST_SENT
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured")
        return False

    with _LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _LAST_SENT)
        if not force and wait > 0:
            time.sleep(wait)
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": str(message)[:4000]},
                timeout=_TIMEOUT,
            )
            if response.status_code == 429:
                retry_after = 2
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", 2))
                except Exception:
                    pass
                time.sleep(min(30, max(1, retry_after)))
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    data={"chat_id": TELEGRAM_CHAT_ID, "text": str(message)[:4000]},
                    timeout=_TIMEOUT,
                )
            response.raise_for_status()
            _LAST_SENT = time.monotonic()
            return response.json()
        except requests.RequestException as error:
            print(f"Telegram alert failed (non-fatal): {error}")
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
