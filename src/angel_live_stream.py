"""Single Angel One SmartWebSocketV2 ingestion service.

The broker SDK expects the JWT as a Bearer token for the streaming endpoint.
This module keeps exactly one socket per process and lets the caller own the
thread lifecycle. It never places orders and only publishes observed ticks.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from src.market_data_bus import publish_tick


DEFAULT_RECONNECT_SECONDS = float(os.getenv("PEREZ_ANGEL_STREAM_RECONNECT_SECONDS", "60"))
DEFAULT_MAX_RETRY = 0


class AngelLiveStream:
    """Own one SmartWebSocketV2 connection and reconnect serially."""

    def __init__(
        self,
        smartapi: Any,
        client_code: str,
        reconnect_seconds: float = DEFAULT_RECONNECT_SECONDS,
        tokens: list[dict[str, Any]] | None = None,
    ) -> None:
        self.smartapi = smartapi
        self.client_code = str(client_code)
        self.reconnect_seconds = max(5.0, float(reconnect_seconds))
        self.tokens = tokens or [
            {"exchangeType": 1, "tokens": ["99926000", "99926009"]},
        ]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: SmartWebSocketV2 | None = None
        self._lock = threading.Lock()
        self._running = False
        self._last_tick_at = 0.0
        self._last_error = ""

    @staticmethod
    def _bearer(token: Any) -> str:
        value = str(token or "").strip()
        if not value:
            return ""
        return value if value.lower().startswith("bearer ") else f"Bearer {value}"

    def _credentials(self) -> tuple[str, str, str, str]:
        auth = self._bearer(getattr(self.smartapi, "access_token", ""))
        api_key = str(getattr(self.smartapi, "api_key", "") or "").strip()
        feed_token = str(getattr(self.smartapi, "feed_token", "") or "").strip()
        client_code = str(getattr(self.smartapi, "userId", "") or self.client_code).strip()
        if not all((auth, api_key, client_code, feed_token)):
            raise RuntimeError("Angel streaming credentials are incomplete")
        return auth, api_key, client_code, feed_token

    def _make_socket(self) -> SmartWebSocketV2:
        auth, api_key, client_code, feed_token = self._credentials()
        socket = SmartWebSocketV2(
            auth,
            api_key,
            client_code,
            feed_token,
            max_retry_attempt=DEFAULT_MAX_RETRY,
            retry_strategy=0,
        )
        socket.on_open = self._on_open
        socket.on_data = self._on_data
        socket.on_error = self._on_error
        socket.on_close = self._on_close
        if hasattr(socket, "on_control_message"):
            socket.on_control_message = self._on_control_message
        return socket

    def _on_open(self, wsapp: Any) -> None:
        print("[ANGEL STREAM] OPEN — single live ingestion active.")
        if self._socket is not None:
            self._socket.subscribe("perez-ai", SmartWebSocketV2.LTP_MODE, self.tokens)

    def _on_data(self, wsapp: Any, message: Any) -> None:
        self._last_tick_at = time.time()
        publish_tick(message)

    def _on_control_message(self, wsapp: Any, message: Any) -> None:
        # Control/heartbeat messages are intentionally not treated as market ticks.
        return

    def _on_error(self, wsapp: Any, error: Any) -> None:
        self._last_error = str(error)
        print(f"[ANGEL STREAM] ERROR type={type(error).__name__} detail={error!r}")

    def _on_close(self, wsapp: Any) -> None:
        print("[ANGEL STREAM] CLOSED")

    def _run(self) -> None:
        self._running = True
        while not self._stop.is_set():
            try:
                print("[ANGEL STREAM] CONNECTING...")
                with self._lock:
                    self._socket = self._make_socket()
                    socket = self._socket
                socket.connect()
            except Exception as exc:
                self._last_error = str(exc)
                print(f"[ANGEL STREAM] CONNECTION FAILED: {exc}")
            finally:
                with self._lock:
                    socket = self._socket
                    self._socket = None
                if socket is not None:
                    try:
                        socket.close_connection()
                    except Exception:
                        pass
            if not self._stop.is_set():
                print(f"[ANGEL STREAM] RECONNECTING IN {int(self.reconnect_seconds)}s")
                self._stop.wait(self.reconnect_seconds)
        self._running = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="perez-angel-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            socket = self._socket
        if socket is not None:
            try:
                socket.close_connection()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._running),
            "connected": bool(self._socket),
            "last_tick_at": self._last_tick_at,
            "last_error": self._last_error,
        }


_stream: AngelLiveStream | None = None


def start_angel_live_stream(smartapi: Any, client_code: str) -> AngelLiveStream:
    global _stream
    if _stream is None:
        _stream = AngelLiveStream(smartapi, client_code)
        _stream.start()
    return _stream


def stop_angel_live_stream() -> None:
    global _stream
    if _stream is not None:
        _stream.stop()
        _stream = None


def get_angel_live_stream() -> AngelLiveStream | None:
    return _stream
