import re
from datetime import datetime
import requests
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _compact_option_id(trade):
    """Return DATE + UNDERLYING + SIDE as one stable Telegram token."""
    symbol = str(trade.get("symbol", "")).strip().upper()
    option_type = str(trade.get("option_type", "")).strip().upper()
    contract = str(trade.get("contract", "")).strip().upper()
    expiry = str(trade.get("expiry", "")).strip().upper()
    if option_type not in {"CE", "PE"}:
        match = re.search(r"(CE|PE)", contract)
        option_type = match.group(1) if match else ""
    match = re.search(r"(\d{1,2})([A-Z]{3})(\d{2})", expiry)
    if not match:
        match = re.search(r"(\d{1,2})([A-Z]{3})(\d{2})", contract)
    if match:
        expiry = f"{int(match.group(1)):02d}{match.group(2)}{match.group(3)}"
    else:
        try:
            parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            expiry = parsed.strftime("%d%b%y").upper()
        except (TypeError, ValueError):
            pass
    return f"{expiry}{symbol}{option_type}" if symbol and option_type and expiry else contract


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


def _entry_reason(trade):
    """Build a concise, evidence-based explanation from validated trade fields."""
    reasons = []
    signal = str(trade.get("signal", "")).upper()
    if signal in {"BUY CE", "BUY PE"}:
        reasons.append(f"Underlying signal {signal}")
    if trade.get("underlying_score") is not None:
        reasons.append(f"underlying score {trade['underlying_score']}/100")
    if trade.get("options_score") is not None:
        reasons.append(f"option gate score {trade['options_score']}/100")
    if trade.get("mtf_direction") and str(trade.get("mtf_direction")).upper() != "MIXED":
        reasons.append(f"MTF {trade['mtf_direction']}")
    if trade.get("strategy"):
        reasons.append(f"strategy {trade['strategy']}")
    return "; ".join(reasons) or "All paper-trade validation gates passed"


def send_entry_alert(trade):
    option_type = str(trade.get("option_type", "")).upper()
    if option_type not in {"CE", "PE"}:
        match = re.search(r"(CE|PE)", str(trade.get("contract", "")).upper())
        option_type = match.group(1) if match else "UNKNOWN"
    strike = trade.get("strike", "UNKNOWN")
    options_score = trade.get("options_score", "N/A")
    underlying_score = trade.get("underlying_score", "N/A")

    return send_alert(
        "🎯 PAPER TRADE CANDIDATE VALIDATED\n\n"
        f"ID: {_compact_option_id(trade)}\n"
        f"Option: {option_type}\n"
        f"Strike: {strike}\n"
        f"Contract: {trade['contract']}\n"
        f"Signal: {trade['signal']}\n"
        f"Option score: {options_score}/100\n"
        f"Underlying score: {underlying_score}/100\n"
        f"Entry: Rs {trade['entry']:.2f}\n"
        f"Quantity: {trade['quantity']}\n"
        f"Stop loss: Rs {trade['stop_loss']:.2f}\n"
        f"Target: Rs {trade['target']:.2f}\n"
        f"Reason: {_entry_reason(trade)}\n\n"
        "🔒 PAPER ONLY — LIVE ORDERS DISABLED"
    )


def send_exit_alert(trade, result):
    label = {
        "TARGET": "TARGET HIT",
        "STOP_LOSS": "STOP LOSS HIT",
        "MARKET_CLOSE": "MARKET CLOSE EXIT",
    }.get(result["exit_reason"], "PAPER TRADE CLOSED")

    return send_alert(
        f"{label}\n\n"
        f"ID: {_compact_option_id(trade)}\n"
        f"Entry: Rs {result['entry']:.2f}\n"
        f"Exit: Rs {result['current']:.2f}\n"
        f"Quantity: {result['quantity']}\n"
        f"P/L: Rs {result['pnl']:.2f} ({result['pnl_percent']:.2f}%)\n"
        f"Reason: {result['exit_reason']}"
    )
