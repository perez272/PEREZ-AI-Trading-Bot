import os
import time
import socket
import json
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.learning_status import get_learning_status

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")
INTERVAL = int(os.getenv("TELEGRAM_UPDATE_INTERVAL", "300"))
IST = ZoneInfo("Asia/Kolkata")
HEARTBEAT_PATH = ROOT / "data" / "runtime" / "heartbeat.json"
TELEGRAM_FINGERPRINT_PATH = ROOT / "data" / "runtime" / "telegram_status_fingerprint.json"


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
            "decision", "status", "source", "timestamp", "threshold", "volume",
            "oi", "iv", "delta", "gamma", "theta", "vega", "volume_ratio",
            "spread_pct", "move_1m_pct", "move_3m_pct", "move_5m_pct",
        )
        used = set()
        for key in preferred:
            if key in event and event[key] not in (None, "", []):
                lines.append(f"   {key}: {_fmt_value(event[key])}")
                used.add(key)
        extra = [k for k in event if k not in used and k != "type" and event[k] not in (None, "", [])]
        for key in extra[:6]:
            lines.append(f"   {key}: {_fmt_value(event[key])}")
    return "\n".join(lines)


def _read_heartbeat():
    try:
        if HEARTBEAT_PATH.exists():
            data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _provider_telemetry():
    """Expose effective configured provider state only; never requests market data."""
    mode = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower() or "auto"
    upstox_enabled = os.getenv("UPSTOX_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    upstox_configured = bool(os.getenv("UPSTOX_ACCESS_TOKEN", "").strip())
    effective_mode = "angel" if mode == "auto" and not upstox_enabled else mode
    return effective_mode, upstox_enabled, upstox_configured


def _scan_message(heartbeat):
    safety = "\n\n🛡️ Scan telemetry is read-only; it does not alter trading or risk decisions."
    if not heartbeat:
        return "🔎 SCAN TELEMETRY\nNo heartbeat scan telemetry persisted yet." + safety

    status = heartbeat.get("status", "unknown")
    lines = [
        "🔎 PEREZ AI — DEEP SCAN TELEMETRY",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Status: {status}",
    ]
    if heartbeat.get("timestamp_utc"):
        lines.append(f"UTC: {heartbeat['timestamp_utc']}")
    if heartbeat.get("next_entry"):
        lines.append(f"Next entry window: {heartbeat['next_entry']}")
    if heartbeat.get("capital") is not None:
        lines.append(f"Capital: Rs {_fmt_value(heartbeat['capital'])}")
    if heartbeat.get("candidates") is not None:
        lines.append(f"Candidates after scan: {heartbeat['candidates']}")

    fields = (
        ("market_data_api_attempts", "API attempts"),
        ("market_data_live_refreshes", "Live refreshes"),
        ("market_data_cache_hits", "Cache hits"),
        ("market_data_fresh_candles", "Fresh candles"),
        ("market_data_fresh_to_decision", "Fresh → decision engine"),
        ("decision_evaluations", "Decision evaluations"),
        ("market_data_blocked_or_failed", "Provider blocked/failed"),
        ("market_data_invalid_or_stale", "Invalid/stale data"),
        ("upstox_fallback_attempts", "Upstox fallback attempts"),
        ("upstox_fallback_successes", "Upstox fallback successes"),
    )
    present = [(label, heartbeat[key]) for key, label in fields if key in heartbeat]
    if present:
        lines.append("")
        lines.append("📡 MARKET-DATA PIPELINE")
        for label, value in present:
            lines.append(f"{label}: {_fmt_value(value)}")

    mode, upstox_enabled, upstox_configured = _provider_telemetry()
    lines.append("")
    lines.append("🔌 PROVIDER ROUTING")
    lines.append(f"Market-data mode: {mode}")
    lines.append(f"Upstox enabled: {'YES' if upstox_enabled else 'NO'}")
    lines.append(f"Upstox credentials configured: {'YES' if upstox_configured else 'NO'}")

    fresh_to_decision = heartbeat.get("market_data_fresh_to_decision")
    blocked = heartbeat.get("market_data_blocked_or_failed")
    if isinstance(fresh_to_decision, (int, float)) and isinstance(blocked, (int, float)) and blocked > 0 and fresh_to_decision == 0:
        lines.append("")
        lines.append("🚫 FAIL-CLOSED MARKET DATA")
        lines.append("No fresh provider data reached the decision engine in this scan.")
        lines.append("No trade decision was allowed from stale/missing data.")

    if heartbeat.get("symbol"):
        lines.append("")
        lines.append("🎯 CURRENT TRADE/DECISION CONTEXT")
        lines.append(f"Symbol: {heartbeat['symbol']}")
    if heartbeat.get("strategy"):
        lines.append(f"Strategy: {heartbeat['strategy']}")
    if heartbeat.get("reason"):
        lines.append(f"Reason: {heartbeat['reason']}")
    if heartbeat.get("error"):
        lines.append(f"⚠️ Error: {heartbeat['error']}")

    return "\n".join(lines) + safety


def _learning_message(learning, heartbeat, now, hostname):
    events = learning.get("last_events", [])
    last_observation = learning.get("last_observation") or "None persisted yet"
    return (
        "🤖 PEREZ AI — DEEP MARKET + LEARNING STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Runtime: ONLINE\n"
        f"🧪 Mode: PAPER TRADING ONLY\n"
        f"🔒 Live orders: DISABLED\n"
        f"🖥️ EC2: {hostname}\n"
        f"⏱️ Telegram snapshot: {now}\n\n"
        f"{_scan_message(heartbeat)}\n\n"
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


def _fingerprint_payload(learning, heartbeat):
    """Use meaningful state only; timestamps alone must not trigger a new message."""
    volatile = {"epoch", "timestamp_utc", "ts", "updated_at", "heartbeat", "telegram_snapshot", "pid"}
    stable_heartbeat = {k: v for k, v in heartbeat.items() if k not in volatile}
    stable_learning = {
        k: v for k, v in learning.items()
        if k not in {"last_observation_time", "generated_at", "telegram_snapshot"}
    }
    mode, upstox_enabled, upstox_configured = _provider_telemetry()
    return {
        "learning": stable_learning,
        "heartbeat": stable_heartbeat,
        "provider": {"mode": mode, "upstox_enabled": upstox_enabled, "upstox_configured": upstox_configured},
        "paper_mode": True,
        "orders_enabled": False,
    }


def _fingerprint(learning, heartbeat):
    payload = json.dumps(_fingerprint_payload(learning, heartbeat), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_fingerprint():
    try:
        if TELEGRAM_FINGERPRINT_PATH.exists():
            data = json.loads(TELEGRAM_FINGERPRINT_PATH.read_text(encoding="utf-8"))
            return str(data.get("fingerprint", "")) if isinstance(data, dict) else ""
    except (OSError, ValueError, TypeError):
        pass
    return ""


def _save_fingerprint(value):
    try:
        TELEGRAM_FINGERPRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = TELEGRAM_FINGERPRINT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fingerprint": value}, separators=(",", ":")), encoding="utf-8")
        tmp.replace(TELEGRAM_FINGERPRINT_PATH)
    except OSError as exc:
        print(f"Telegram dedup state write failed: {exc}", flush=True)


def send_status():
    if not CHAT_ID:
        raise RuntimeError("Telegram chat ID not found in .env")

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    hostname = socket.gethostname()
    learning = get_learning_status()
    heartbeat = _read_heartbeat()
    fingerprint = _fingerprint(learning, heartbeat)
    if fingerprint == _last_fingerprint():
        return False

    message = _learning_message(learning, heartbeat, now, hostname)
    telegram("sendMessage", {"chat_id": CHAT_ID, "text": message})
    _save_fingerprint(fingerprint)
    return True


def main():
    print("PEREZ AI independent Telegram updater starting", flush=True)
    me = telegram("getMe", {})
    bot_name = me["result"].get("username", "unknown")
    print(f"Telegram API OK — @{bot_name}", flush=True)
    if send_status():
        print("Initial Telegram heartbeat sent", flush=True)
    else:
        print("Initial Telegram heartbeat unchanged; not sent", flush=True)

    while True:
        time.sleep(INTERVAL)
        try:
            if send_status():
                print("Telegram heartbeat sent", flush=True)
            else:
                print("Telegram heartbeat unchanged; not sent", flush=True)
        except Exception as exc:
            print(f"Telegram heartbeat failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
