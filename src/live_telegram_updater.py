import os
import time
import socket
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from src.ai_memory import memory_status

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
    memory = memory_status()
    message = (
        "🤖 PEREZ AI BOT STATUS\n\n"
        "🟢 Runtime: ONLINE\n"
        "🧠 Mode: PAPER TRADING ONLY\n"
        "🔒 Live orders: DISABLED\n"
        f"🖥️ EC2: {hostname}\n"
        f"⏱️ Heartbeat: {now}\n"
        "🛡️ Trading engine: PROTECTED\n\n"
        "🧠 LEARNING MEMORY\n"
        f"Completed paper trades: {memory['completed_trades']}\n"
        f"Wins: {memory['wins']}\n"
        f"Learned win rate: {memory['win_rate_pct']:.2f}%\n"
        f"Learned P/L: Rs {memory['pnl']:.2f}\n"
        f"Observations: {memory['observations']}\n"
        f"Rejections: {memory['rejections']}\n"
        f"Lessons/events: {memory['lessons']}\n"
        f"Option surge events: {memory['surge_events']}\n"
        f"Outcome learning: {memory['outcome_learning']}\n"
        f"Pattern learning: {memory['pattern_learning']}\n\n"
        "💡 AI: learning only from genuine persisted market evidence and closed paper trades; risk gates cannot be bypassed."
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
