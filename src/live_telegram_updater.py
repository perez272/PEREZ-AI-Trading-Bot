import os
import time
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.learning_status import get_learning_status

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
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
    learning = get_learning_status()
    last_events = learning.get("last_events", [])
    event_line = "None"
    if last_events:
        event_line = ", ".join(str(e.get("type", "EVENT")) for e in last_events[-3:])

    message = (
        "🤖 PEREZ AI BOT STATUS\n\n"
        "🟢 Runtime: ONLINE\n"
        "🧠 Mode: PAPER TRADING ONLY\n"
        "🔒 Live orders: DISABLED\n"
        f"🖥️ EC2: {hostname}\n"
        f"⏱️ Heartbeat: {now}\n"
        "🛡️ Trading engine: PROTECTED\n\n"
        "🧠 LEARNING MEMORY\n"
        f"Completed paper trades: {learning['completed_paper_trades']}\n"
        f"Wins: {learning['wins']}\n"
        f"Learned win rate: {learning['learned_win_rate']:.2f}%\n"
        f"Learned P/L: Rs {learning['learned_pnl']:.2f}\n"
        f"Observations: {learning['observations']}\n"
        f"Rejections: {learning['rejections']}\n"
        f"Lessons/events: {learning['lessons_events']}\n"
        f"Option surge events: {learning['option_surge_events']}\n"
        f"Outcome learning: {learning['outcome_learning']}\n"
        f"Pattern learning: {learning['pattern_learning']}\n"
        f"Recent evidence: {event_line}\n\n"
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
