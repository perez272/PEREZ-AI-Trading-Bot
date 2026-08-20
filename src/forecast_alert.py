"""Telegram formatting/deduplication for Future Value Engine forecasts."""
from __future__ import annotations

import time
from typing import Any, Dict

from src.future_value_engine import forecast
from src.news_engine import search_symbol_news
from src.telegram_alert import send_alert

_LAST: Dict[str, float] = {}
COOLDOWN_SECONDS = 15 * 60
MIN_CONFIDENCE = 70.0
MIN_DIRECTIONAL_EDGE = 18.0


def build_forecast_alert(candidate: Dict[str, Any], *, horizon: str = "2h") -> Dict[str, Any]:
    symbol = str(candidate.get("symbol") or candidate.get("underlying") or "").upper()
    news = search_symbol_news(symbol)
    result = forecast(candidate, horizon=horizon, news=news)
    if not result.get("eligible"):
        return result
    result["news"] = news
    return result


def maybe_send_forecast_alert(candidate: Dict[str, Any], *, horizon: str = "2h") -> bool:
    result = build_forecast_alert(candidate, horizon=horizon)
    if not result.get("eligible"):
        return False
    f = result["forecast"]
    edge = abs(f["probability_up"] - 50.0)
    if f["confidence"] < MIN_CONFIDENCE or edge < MIN_DIRECTIONAL_EDGE:
        return False

    asset_type = str(f.get("asset_type", "equity"))
    key = f"{f['symbol']}:{asset_type}:{candidate.get('option_type', '')}:{f['direction']}:{horizon}"
    now = time.time()
    if now - _LAST.get(key, 0.0) < COOLDOWN_SECONDS:
        return False

    drivers = ", ".join(f["drivers"]) or "none"
    blockers = ", ".join(f["blockers"]) or "none"
    contract = str(candidate.get("contract") or "").strip()
    contract_line = f"Contract: {contract}\n" if contract else ""
    message = (
        "PEREZ AI FUTURE VALUE ALERT\n\n"
        f"Selected: {f['symbol']} ({f['asset_type']})\n"
        f"{contract_line}"
        f"Horizon: {f['horizon']}\n"
        f"Direction: {f['direction']}\n"
        f"Current: Rs {f['current_price']:.2f}\n"
        f"Upside probability: {f['probability_up']:.1f}%\n"
        f"Downside probability: {f['probability_down']:.1f}%\n"
        f"Confidence: {f['confidence']:.1f}/100\n"
        f"Expected range: Rs {f['expected_low']:.2f} - Rs {f['expected_high']:.2f}\n"
        f"Target estimate: Rs {f['target']:.2f}\n"
        f"Invalidation: Rs {f['invalidation']:.2f}\n"
        f"Drivers: {drivers}\n"
        f"Blockers: {blockers}\n"
        f"News items: {result['news'].get('count', 0)}\n"
        "PAPER MODE — forecast only; no live order."
    )
    sent = bool(send_alert(message))
    if sent:
        _LAST[key] = now
    return sent
