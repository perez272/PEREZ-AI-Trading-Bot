import os
import time
import socket
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
INTERVAL = int(os.getenv("TELEGRAM_UPDATE_INTERVAL", "300"))
IST = ZoneInfo("Asia/Kolkata")


def telegram(method, payload):
    if not TOKEN:
        raise RuntimeError("Telegram bot token not found in .env")
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def send_status():
    if not CHAT_ID:
        raise RuntimeError("Telegram chat ID not found in .env")

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    hostname = socket.gethostname()

    message = (
        "🤖 PEREZ AI BOT STATUS\n\n"
        "Runtime: ONLINE\n"
        "Mode: PAPER TRADING ONLY\n"
        "Live orders: DISABLED\n"
        f"EC2: {hostname}\n"
        f"Heartbeat: {now}\n"
        "Trading engine: protected\n"
    )

    telegram("sendMessage", {
        "chat_id": CHAT_ID,
        "text": message,
    })


def main():
    print("PEREZ AI independent Telegram updater starting", flush=True)

    # Startup/API validation
    me = telegram("getMe", {})
    bot_name = me["result"].get("username", "unknown")
    print(f"Telegram API OK — @{bot_name}", flush=True)

    # Immediate heartbeat
    send_status()
    print("Initial Telegram heartbeat sent", flush=True)

    while True:
        time.sleep(INTERVAL)
        try:
            send_status()
            print("Telegram heartbeat sent", flush=True)
        except Exception as exc:
            print(f"Telegram heartbeat failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
