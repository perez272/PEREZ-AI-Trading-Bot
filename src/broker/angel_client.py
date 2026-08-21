import json
import os
import time
from collections import deque
from contextlib import contextmanager
from threading import Lock

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


class AngelClient:
    # Conservative pacing for Angel One historical/market-data traffic.
    CANDLE_REQUEST_INTERVAL = 3.0
    MARKET_DATA_REQUEST_INTERVAL = 3.0

    # Global rolling market-data budget. The in-process deque is supplemented
    # by a file-backed ledger so the budget is shared by perez-ai.service,
    # telegram/live updater processes, and any other local AngelClient process.
    MARKET_DATA_BUDGET_WINDOW = 60.0
    MARKET_DATA_BUDGET_MAX_REQUESTS = 12
    MARKET_DATA_BUDGET_FILE = "/tmp/perez_ai_market_data_budget.json"
    _GLOBAL_MARKET_DATA_REQUESTS = deque()
    _GLOBAL_MARKET_DATA_LOCK = Lock()

    # Shared cooldown prevents another process from immediately hammering
    # Angel One after any process receives a rate-limit response.
    RATE_LIMIT_COOLDOWN = 90.0

    def __init__(self, smartapi, session_manager=None):
        self.api = smartapi
        self.session_manager = session_manager
        self._last_candle_request = 0.0
        self._last_market_data_request = 0.0

    @contextmanager
    def _budget_file_lock(self):
        os.makedirs(os.path.dirname(self.MARKET_DATA_BUDGET_FILE), exist_ok=True)
        with open(self.MARKET_DATA_BUDGET_FILE, "a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_shared_state(self, handle):
        handle.seek(0)
        raw = handle.read().strip()
        if not raw:
            return {"requests": [], "cooldown_until": 0.0}
        try:
            state = json.loads(raw)
            requests = [float(x) for x in state.get("requests", [])]
            return {
                "requests": requests,
                "cooldown_until": float(state.get("cooldown_until", 0.0)),
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"requests": [], "cooldown_until": 0.0}

    def _write_shared_state(self, handle, state):
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())

    def _shared_cooldown_remaining(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            remaining = max(0.0, float(state.get("cooldown_until", 0.0)) - now)
            return remaining

    def _set_rate_limit_cooldown(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            state["cooldown_until"] = max(
                float(state.get("cooldown_until", 0.0)),
                now + self.RATE_LIMIT_COOLDOWN,
            )
            self._write_shared_state(handle, state)

    def _is_invalid_token(self, response=None, error=None):
        text = ""
        if error is not None:
            text += " " + str(error)
        if response is not None:
            text += " " + str(response)
        text = text.lower()
        return (
            "invalid token" in text
            or "ag8001" in text
            or "jwt" in text
            or "token expired" in text
        )

    def _is_rate_limited(self, response=None, error=None):
        text = ""
        if error is not None:
            text += " " + str(error)
        if response is not None:
            text += " " + str(response)
        text = text.lower()
        return (
            "access rate" in text
            or "rate limit" in text
            or "too many requests" in text
            or "ab1021" in text
            or "exceeding access rate" in text
        )

    def refresh_session(self):
        if not self.session_manager:
            return False
        print("[AUTH] Refreshing Angel One session...")
        try:
            self.api = self.session_manager.refresh()
            print("[AUTH] Session refreshed successfully.")
            return True
        except Exception as e:
            print(f"[AUTH] Session refresh failed: {e}")
            return False

    def _retry(self, func, *args, **kwargs):
        """Call SmartAPI defensively without creating a rate-limit crash loop."""
        remaining = self._shared_cooldown_remaining()
        if remaining > 0:
            print(f"[API RATE LIMIT] Global cooldown active — skipping request ({int(remaining)}s remaining).")
            return None

        token_refresh_attempted = False
        for attempt in range(2):
            try:
                response = func(*args, **kwargs)
                if response is None:
                    print("[API] Empty response — skipping request.")
                    return None

                if self._is_invalid_token(response=response):
                    if self.session_manager and not token_refresh_attempted:
                        token_refresh_attempted = True
                        if self.refresh_session():
                            method_name = getattr(func, "__name__", None)
                            if method_name:
                                func = getattr(self.api, method_name)
                            continue
                    print("[AUTH] Invalid token and session refresh failed.")
                    return None

                if self._is_rate_limited(response=response):
                    self._set_rate_limit_cooldown()
                    print(
                        "[API RATE LIMIT] Angel One rejected request. "
                        f"Global market-data cooldown active for {self.RATE_LIMIT_COOLDOWN:.0f}s."
                    )
                    return None

                return response

            except Exception as e:
                if self._is_invalid_token(error=e):
                    if self.session_manager and not token_refresh_attempted:
                        token_refresh_attempted = True
                        if self.refresh_session():
                            method_name = getattr(func, "__name__", None)
                            if method_name:
                                func = getattr(self.api, method_name)
                            continue
                    print("[AUTH] Could not refresh Angel One session.")
                    return None

                if self._is_rate_limited(error=e):
                    self._set_rate_limit_cooldown()
                    print(
                        "[API RATE LIMIT] Angel One rejected request. "
                        f"Global market-data cooldown active for {self.RATE_LIMIT_COOLDOWN:.0f}s."
                    )
                    return None

                print(f"[API attempt {attempt + 1}/2] {e}")
                if attempt == 0:
                    time.sleep(4)

        print("[API] Request failed after retries — skipping.")
        return None

    @classmethod
    def _prune_global_market_data_budget(cls, now=None):
        now = time.monotonic() if now is None else now
        cutoff = now - cls.MARKET_DATA_BUDGET_WINDOW
        with cls._GLOBAL_MARKET_DATA_LOCK:
            while cls._GLOBAL_MARKET_DATA_REQUESTS and cls._GLOBAL_MARKET_DATA_REQUESTS[0] <= cutoff:
                cls._GLOBAL_MARKET_DATA_REQUESTS.popleft()

    def _market_data_budget_available(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
            requests = [x for x in state["requests"] if x > cutoff]
            state["requests"] = requests
            remaining_cooldown = max(0.0, state["cooldown_until"] - now)
            if remaining_cooldown > 0:
                print(f"[API RATE LIMIT] Global cooldown active — skipping request ({int(remaining_cooldown)}s remaining).")
                self._write_shared_state(handle, state)
                return False
            if len(requests) >= self.MARKET_DATA_BUDGET_MAX_REQUESTS:
                oldest = requests[0]
                retry_in = max(0, int(self.MARKET_DATA_BUDGET_WINDOW - (now - oldest)))
                print(
                    "[MARKET DATA BUDGET] Global request budget exhausted — "
                    f"{len(requests)}/{self.MARKET_DATA_BUDGET_MAX_REQUESTS} requests in "
                    f"{self.MARKET_DATA_BUDGET_WINDOW:.0f}s; retry in ~{retry_in}s."
                )
                self._write_shared_state(handle, state)
                return False
            return True

    def _record_market_data_request(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
            state["requests"] = [x for x in state["requests"] if x > cutoff]
            state["requests"].append(now)
            self._write_shared_state(handle, state)

    def _prepare_market_data_request(self, last_request_attr, interval):
        remaining = self._shared_cooldown_remaining()
        if remaining > 0:
            print(f"[API RATE LIMIT] Global cooldown active — skipping request ({int(remaining)}s remaining).")
            return False

        last_request = getattr(self, last_request_attr)
        elapsed = time.monotonic() - last_request
        if elapsed < interval:
            print(
                f"[MARKET DATA PACE] Request skipped — "
                f"{interval - elapsed:.1f}s until next permitted request."
            )
            return False

        # Reserve the global budget atomically before making the API call.
        if not self._market_data_budget_available():
            return False
        self._record_market_data_request()
        setattr(self, last_request_attr, time.monotonic())
        return True

    def get_candles(self, params):
        if not self._prepare_market_data_request("_last_candle_request", self.CANDLE_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.getCandleData, params)

    def get_ltp(self, exchange, symbol, token):
        if not self._prepare_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.ltpData, exchange, symbol, token)

    def get_rms_limit(self):
        return self._retry(self.api.rmsLimit)

    def get_market_data(self, mode, exchange_tokens):
        if not self._prepare_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.getMarketData, mode, exchange_tokens)
