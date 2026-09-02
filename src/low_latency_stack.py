"""PEREZ AI low-latency market-data shadow stack.

Safe by design: market-data streaming and leading-signal calculation only.
It never places, cancels, or replaces broker orders.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional


@dataclass(frozen=True)
class LeadingSignal:
    side: str
    imbalance: float
    price_change_pct: float
    volume_ratio: float
    strength: float


def order_flow_imbalance(buy_qty: float, sell_qty: float) -> float:
    total = float(buy_qty) + float(sell_qty)
    if total <= 0:
        return 0.0
    return (float(buy_qty) - float(sell_qty)) / total


class LeadingSignalEngine:
    """Small, deterministic tick feature engine; no trading side effects."""

    def __init__(self, window: int = 20) -> None:
        self.prices: Deque[float] = deque(maxlen=window)
        self.volumes: Deque[float] = deque(maxlen=window)

    def update(self, price: float, buy_qty: float = 0.0, sell_qty: float = 0.0,
               volume: float = 0.0) -> Optional[LeadingSignal]:
        price = float(price)
        if price <= 0:
            return None
        prev = self.prices[-1] if self.prices else price
        self.prices.append(price)
        self.volumes.append(max(0.0, float(volume)))
        if len(self.prices) < 2:
            return None
        move = ((price - prev) / prev) * 100.0 if prev else 0.0
        imbalance = order_flow_imbalance(buy_qty, sell_qty)
        positive_vols = [v for v in self.volumes if v > 0]
        avg_vol = sum(positive_vols[:-1]) / max(1, len(positive_vols) - 1) if len(positive_vols) > 1 else 0.0
        volume_ratio = (self.volumes[-1] / avg_vol) if avg_vol > 0 else 0.0
        strength = abs(imbalance) * 0.6 + min(abs(move) / 0.2, 1.0) * 0.2 + min(volume_ratio / 3.0, 1.0) * 0.2
        if imbalance >= 0.35 and move > 0:
            side = "BULLISH_SURGE"
        elif imbalance <= -0.35 and move < 0:
            side = "BEARISH_SURGE"
        else:
            side = "NEUTRAL"
        return LeadingSignal(side, imbalance, move, volume_ratio, strength)


class AsyncTickBridge:
    """Bridge Angel SmartWebSocketV2 callbacks into an asyncio queue.

    The Angel SDK owns the websocket thread; callbacks only enqueue data and
    return immediately. This keeps the trading event loop non-blocking.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, max_queue: int = 5000) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue)
        self.latest: dict[str, dict[str, Any]] = {}
        self.last_tick_monotonic = 0.0
        self.dropped_ticks = 0
        self._lock = threading.Lock()

    def on_data(self, _wsapp: Any, message: Any) -> None:
        if not isinstance(message, dict):
            return
        item = dict(message)
        item["received_monotonic"] = time.monotonic()
        token = str(item.get("token", ""))
        with self._lock:
            self.last_tick_monotonic = item["received_monotonic"]
            if token:
                self.latest[token] = item
        self.loop.call_soon_threadsafe(self._enqueue, item)

    def _enqueue(self, item: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped_ticks += 1

    async def get(self) -> dict[str, Any]:
        return await self.queue.get()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age_ms = ((time.monotonic() - self.last_tick_monotonic) * 1000.0
                      if self.last_tick_monotonic else None)
            return {"latest_tokens": len(self.latest), "tick_age_ms": age_ms,
                    "dropped_ticks": self.dropped_ticks}


def start_angel_websocket(sws: Any, bridge: AsyncTickBridge,
                          token_list: list[dict[str, Any]], mode: int = 1,
                          correlation_id: str = "PEREZAI001",
                          on_error: Optional[Callable[..., Any]] = None) -> threading.Thread:
    """Start SmartWebSocketV2 in a daemon thread (shadow mode only)."""
    sws.on_data = bridge.on_data

    def _open(wsapp: Any) -> None:
        sws.subscribe(correlation_id, mode, token_list)

    sws.on_open = _open
    if on_error is not None:
        sws.on_error = on_error
    thread = threading.Thread(target=sws.connect, name="perez-smartws", daemon=True)
    thread.start()
    return thread
