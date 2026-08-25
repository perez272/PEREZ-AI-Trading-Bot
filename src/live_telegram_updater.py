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


def _fmt_value(value):
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def _event_details(events):
    if not events:
        return "No persisted events yet."
    lines = []
    for idx, event in enumerate(events[-3:], 1):
        if not isinstance(event, dict):
            lines.append(f"{idx}. {event}")
            continue
        event_type = event.get("type", "EVENT")
        lines.append(f"{idx}. {event_type}")
        preferred = (
            "symbol", "contract", "option_type", "signal", "direction", "price",
            "ltp", "move_pct", "surge_pct", "score", "confidence", "reason",
            "decision", "status", "source", "timestamp",
        )
        used = set()
        for key in preferred:
            if key in event and event[key] not in (None, "", []):
                lines.append(f"   {key}: {_fmt_value(event[key])}")
                used.add(key)
        extra = [k for k in event if k not in used and k != "type" and event[k] not in (None, "", [])]
        for key in extra[:8]:
            lines.append(f"   {key}: {_fmt_value(event[key])}")
    return "\n".join(lines)


def _learning_message(learning, now, hostname):
    events = learning.get("last_events", [])
    last_observation = learning.get("last_observation") or "None persisted yet"
    return (
        "🤖 PEREZ AI — DEEP LEARNING STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Runtime: ONLINE\n"
        f"🧪 Mode: PAPER TRADING ONLY\n"
        f"🔒 Live orders: DISABLED\n"
        f"🖥️ EC2: {hostname}\n"
        f"⏱️ Telegram snapshot: {now}\n\n"
        "🧠 PERSISTED LEARNING\n"
        f"Closed paper trades: {learning['completed_paper_trades']}\n"
        f"Wins: {learning['wins']}\n"
        f"Learned win rate: {learning['learned_win_rate']:.2f}%\n"
        f"Learned P/L: Rs {learning['learned_pnl']:.2f}\n"
        f"Market observations: {learning['observations']}\n"
        f"Rejections: {learning['rejections']}\n"
        f"Lessons/events: {learning['lessons_events']}\n"
        f"Option surge events: {learning['option_surge_events']}\n"
        f"Outcome learning: {learning['outcome_learning']}\n"
        f"Pattern learning: {learning['pattern_learning']}\n"
        f"Last observation: {last_observation}\n\n"
        "🔎 RECENT PERSISTED EVIDENCE\n"
        f"{_event_details(events)}\n\n"
        "🧠 LEARNING RULE\n"
        "Only persisted market evidence and closed paper-trade outcomes are used. "
        "Learning is observational; it cannot bypass risk gates or enable live orders."
    )


def send_status():
    if not CHAT_ID:
        raise RuntimeError("Telegram chat ID not found in .env")

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    hostname = socket.gethostname()
    learning = get_learning_status()
    message = _learning_message(learning, now, hostname)
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
