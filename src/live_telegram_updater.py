import os
import time
import socket
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from src.ai_memory import learning_summary

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
INTERVAL = int(os.getenv("TELEGRAM_UPDATE_INTERVAL", "300"))
IST = ZoneInfo("Asia/Kolkata")


def telegram(method, payload):
    if not TOKEN:
        raise RuntimeError("Telegram bot token not found in .env")
    response = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=payload, timeout=15)
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
    stats = learning_summary()["overall"]
    n = int(stats["n"])
    wins = int(stats["wins"])
    win_rate = (wins / n * 100) if n else 0
    message = (
        "🤖 PEREZ AI BOT STATUS\n\n"
        "🟢 Runtime: ONLINE\n"
        "🧠 Mode: PAPER TRADING ONLY\n"
        "🔒 Live orders: DISABLED\n"
        f"🖥️ EC2: {hostname}\n"
        f"⏱️ Heartbeat: {now}\n"
        "🛡️ Trading engine: PROTECTED\n\n"
        "🧠 LEARNING MEMORY\n"
        f"Completed paper trades: {n}\n"
        f"Learned win rate: {win_rate:.0f}%\n"
        f"Learned P/L: Rs {float(stats['pnl']):.2f}\n\n"
        "💡 AI: learning from completed paper-trade outcomes; risk gates cannot be bypassed."
    )
    telegram("sendMessage", {"chat_id": CHAT_ID, "text": message})


def main():
    print("PEREZ AI independent Telegram updater starting", flush=True)
    me = telegram("getMe", {})
    bot_name = me["result"].get("username", "unknown")
    print(f"Telegram API OK — @{bot_name}", flush=True)
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
