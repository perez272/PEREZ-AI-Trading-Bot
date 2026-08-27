import json
import os
import time
from contextlib import contextmanager
from threading import Lock

try:
    import fcntl
except ImportError:
    fcntl = None


class AngelClient:
    # Angel's published getCandleData limit is 3 requests/second and 150/minute.
    # Use conservative spacing and a shared rolling budget so multiple client
    # instances/processes cannot burst the same Angel account.
    CANDLE_REQUEST_INTERVAL = 2.0
    MARKET_DATA_REQUEST_INTERVAL = 1.0
    MARKET_DATA_BUDGET_WINDOW = 60.0
    MARKET_DATA_BUDGET_MAX_REQUESTS = 12
    MARKET_DATA_BUDGET_FILE = "/tmp/perez_ai_market_data_budget.json"

    # A single endpoint rejection gets an endpoint-local cooldown.  A global
    # account breaker is armed only after repeated rate-limit responses in the
    # same short window, preventing one false-positive from freezing candles.
    ENDPOINT_RATE_LIMIT_COOLDOWN = 60.0
    RATE_LIMIT_COOLDOWN = 300.0
    RATE_LIMIT_EVENT_WINDOW = 300.0
    RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER = 3

    CANDLE_RATE_LIMIT_COOLDOWN = float(os.getenv("CANDLE_RATE_LIMIT_COOLDOWN", "300.0"))
    CANDLE_COOLDOWN_FILE = "/tmp/perez_ai_candle_rate_limit.json"
    _GLOBAL_MARKET_DATA_LOCK = Lock()

    def __init__(self, smartapi, session_manager=None):
        self.api = smartapi
        self.session_manager = session_manager
        self._last_candle_request = 0.0
        self._last_market_data_request = 0.0

    @contextmanager
    def _budget_file_lock(self):
        directory = os.path.dirname(self.MARKET_DATA_BUDGET_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.MARKET_DATA_BUDGET_FILE, "a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _candle_cooldown_lock(self):
        directory = os.path.dirname(self.CANDLE_COOLDOWN_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.CANDLE_COOLDOWN_FILE, "a+", encoding="utf-8") as handle:
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
            return {
                "requests": [],
                "cooldown_until": 0.0,
                "last_request_at": 0.0,
                "market_data_cooldown_until": 0.0,
                "rate_limit_events": [],
                "global_breaker_armed": False,
            }
        try:
            state = json.loads(raw)
            return {
                "requests": [float(x) for x in state.get("requests", [])],
                "cooldown_until": float(state.get("cooldown_until", 0.0)),
                "last_request_at": float(state.get("last_request_at", 0.0)),
                "market_data_cooldown_until": float(state.get("market_data_cooldown_until", 0.0)),
                "rate_limit_events": [float(x) for x in state.get("rate_limit_events", [])],
                "global_breaker_armed": bool(state.get("global_breaker_armed", False)),
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return {
                "requests": [],
                "cooldown_until": 0.0,
                "last_request_at": 0.0,
                "market_data_cooldown_until": 0.0,
                "rate_limit_events": [],
                "global_breaker_armed": False,
            }

    def _write_shared_state(self, handle, state):
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())

    def _read_candle_cooldown_until(self):
        try:
            with self._candle_cooldown_lock() as handle:
                handle.seek(0)
                raw = handle.read().strip()
                if not raw:
                    return 0.0
                value = json.loads(raw)
                return float(value.get("candle_cooldown_until", 0.0)) if isinstance(value, dict) else float(value)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return 0.0

    def _shared_candle_cooldown_remaining(self):
        remaining = max(0.0, self._read_candle_cooldown_until() - time.monotonic())
        if remaining > self.CANDLE_RATE_LIMIT_COOLDOWN:
            return 0.0
        return remaining

    def _set_candle_rate_limit_cooldown(self):
        now = time.monotonic()
        try:
            with self._candle_cooldown_lock() as handle:
                handle.seek(0)
                raw = handle.read().strip()
                current = 0.0
                if raw:
                    try:
                        value = json.loads(raw)
                        current = float(value.get("candle_cooldown_until", 0.0)) if isinstance(value, dict) else float(value)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                new_until = now + self.CANDLE_RATE_LIMIT_COOLDOWN
                if current > now + self.CANDLE_RATE_LIMIT_COOLDOWN:
                    current = 0.0
                handle.seek(0)
                handle.truncate()
                json.dump({"candle_cooldown_until": max(current, new_until)}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            print(f"[CANDLE RATE LIMIT] Could not persist endpoint cooldown: {exc}")

    def _shared_cooldown_remaining(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)

            # Only an explicitly armed breaker is a global breaker.
            # Legacy cooldown-only state must never freeze fresh candle
            # ingestion after a restart/deployment.
            if not state.get("global_breaker_armed", False):
                if state["cooldown_until"] != 0.0:
                    state["cooldown_until"] = 0.0
                    self._write_shared_state(handle, state)
                return 0.0

            remaining = max(0.0, state["cooldown_until"] - now)
            if remaining <= 0:
                state["cooldown_until"] = 0.0
                state["global_breaker_armed"] = False
                self._write_shared_state(handle, state)
                return 0.0

            return remaining

    def market_data_status(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
            state["requests"] = [x for x in state["requests"] if x > cutoff]
            event_cutoff = now - self.RATE_LIMIT_EVENT_WINDOW
            state["rate_limit_events"] = [x for x in state["rate_limit_events"] if x > event_cutoff]
            if not state.get("global_breaker_armed", False):
                state["cooldown_until"] = 0.0
            elif state["cooldown_until"] <= now:
                state["cooldown_until"] = 0.0
                state["global_breaker_armed"] = False
            self._write_shared_state(handle, state)
            return {
                "cooldown_remaining": max(0.0, state["cooldown_until"] - now),
                "market_data_cooldown_remaining": max(0.0, state["market_data_cooldown_until"] - now),
                "candle_cooldown_remaining": self._shared_candle_cooldown_remaining(),
                "requests_in_window": len(state["requests"]),
                "requests_remaining": max(0, self.MARKET_DATA_BUDGET_MAX_REQUESTS - len(state["requests"])),
                "rate_limit_events": len(state["rate_limit_events"]),
            }

    def _record_rate_limit(self, endpoint):
        """
        Record broker rate-limit events with endpoint isolation.

        Historical candle throttles are endpoint-local and MUST NOT
        contribute to the global market-data circuit breaker. This keeps
        live quote/RMS paths available when Angel One throttles candles.
        """
        now = time.monotonic()

        # Candle throttling is deliberately isolated from the global
        # market-data breaker.
        if endpoint == "candle":
            self._set_candle_rate_limit_cooldown()
            return False, 0

        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)

            cutoff = now - self.RATE_LIMIT_EVENT_WINDOW
            events = [
                x for x in state["rate_limit_events"]
                if x > cutoff
            ]
            events.append(now)
            state["rate_limit_events"] = events

            endpoint_until = now + self.ENDPOINT_RATE_LIMIT_COOLDOWN

            if endpoint == "market_data":
                state["market_data_cooldown_until"] = max(
                    state["market_data_cooldown_until"],
                    endpoint_until,
                )

            # Only non-candle market-data rate limits can arm the global
            # breaker. Candle failures are endpoint-local by design.
            if len(events) >= self.RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER:
                state["cooldown_until"] = max(
                    state["cooldown_until"],
                    now + self.RATE_LIMIT_COOLDOWN,
                )
                state["global_breaker_armed"] = True
                global_armed = True
            else:
                global_armed = False

            self._write_shared_state(handle, state)
            return global_armed, len(events)

    def _set_rate_limit_cooldown(self):
        # Backward-compatible helper: callers that explicitly request the
        # global breaker still get the full circuit-breaker duration.
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            state["cooldown_until"] = max(
                state["cooldown_until"], now + self.RATE_LIMIT_COOLDOWN
            )
            state["global_breaker_armed"] = True
            self._write_shared_state(handle, state)

    def _is_invalid_token(self, response=None, error=None):
        text = f"{error or ''} {response or ''}".lower()
        return "invalid token" in text or "ag8001" in text or "jwt" in text or "token expired" in text

    def _is_rate_limited(self, response=None, error=None):
        text = f"{error or ''} {response or ''}".lower()
        return "access rate" in text or "rate limit" in text or "too many requests" in text or "ab1021" in text or "exceeding access rate" in text

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

    def _endpoint_cooldown_remaining(self, endpoint):
        now = time.monotonic()
        if endpoint == "candle":
            return self._shared_candle_cooldown_remaining()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            return max(0.0, state["market_data_cooldown_until"] - now)

    def _retry(self, func, *args, endpoint="market_data", **kwargs):
        remaining = self._shared_cooldown_remaining()
        if remaining > 0:
            print(f"[API RATE LIMIT] Global cooldown active — skipping request ({int(remaining)}s remaining).")
            return None
        endpoint_remaining = self._endpoint_cooldown_remaining(endpoint)
        if endpoint_remaining > 0:
            label = "CANDLE RATE LIMIT" if endpoint == "candle" else "MARKET DATA RATE LIMIT"
            print(f"[{label}] Endpoint cooldown active — skipping request ({int(endpoint_remaining)}s remaining).")
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
                    global_armed, count = self._record_rate_limit(endpoint)
                    if global_armed:
                        print(f"[API RATE LIMIT] Angel One rejected request. Global circuit breaker armed for {self.RATE_LIMIT_COOLDOWN:.0f}s after {count} rate-limit events.")
                    elif endpoint == "candle":
                        print(f"[CANDLE RATE LIMIT] Angel One rejected candle request. Endpoint cooldown {self.CANDLE_RATE_LIMIT_COOLDOWN:.0f}s; global breaker not armed ({count}/{self.RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER}).")
                    else:
                        print(f"[MARKET DATA RATE LIMIT] Angel One rejected request. Endpoint cooldown {self.ENDPOINT_RATE_LIMIT_COOLDOWN:.0f}s; global breaker not armed ({count}/{self.RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER}).")
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
                    global_armed, count = self._record_rate_limit(endpoint)
                    if global_armed:
                        print(f"[API RATE LIMIT] Angel One rejected request. Global circuit breaker armed for {self.RATE_LIMIT_COOLDOWN:.0f}s after {count} rate-limit events.")
                    elif endpoint == "candle":
                        print(f"[CANDLE RATE LIMIT] Angel One rejected candle request. Endpoint cooldown {self.CANDLE_RATE_LIMIT_COOLDOWN:.0f}s; global breaker not armed ({count}/{self.RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER}).")
                    else:
                        print(f"[MARKET DATA RATE LIMIT] Angel One rejected request. Endpoint cooldown {self.ENDPOINT_RATE_LIMIT_COOLDOWN:.0f}s; global breaker not armed ({count}/{self.RATE_LIMIT_EVENTS_FOR_GLOBAL_BREAKER}).")
                    return None
                print(f"[API attempt {attempt + 1}/2] {e}")
                if attempt == 0:
                    time.sleep(4)
        print("[API] Request failed after retries — skipping.")
        return None

    def _reserve_market_data_request(self, last_request_attr, interval):
        # Local monotonic spacing plus a shared timestamp protects multiple
        # AngelClient instances/processes using the same account.
        while True:
            now = time.monotonic()
            local_remaining = interval - (now - getattr(self, last_request_attr))
            sleep_for = max(0.0, local_remaining)
            with self._budget_file_lock() as handle:
                state = self._read_shared_state(handle)
                cooldown_remaining = (
                    max(0.0, state["cooldown_until"] - now)
                    if state.get("global_breaker_armed", False)
                    else 0.0
                )
                if cooldown_remaining > 0:
                    print(
                        f"[API RATE LIMIT] Global cooldown active — skipping request "
                        f"({int(cooldown_remaining)}s remaining)."
                    )
                    return False
                shared_remaining = max(0.0, interval - (now - state["last_request_at"]))
                sleep_for = max(sleep_for, shared_remaining)
                if sleep_for <= 0:
                    cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
                    requests = [x for x in state["requests"] if x > cutoff]
                    state["requests"] = requests
                    if len(requests) >= self.MARKET_DATA_BUDGET_MAX_REQUESTS:
                        retry_in = max(0, int(self.MARKET_DATA_BUDGET_WINDOW - (now - requests[0])))
                        print(f"[MARKET DATA BUDGET] Global request budget exhausted — {len(requests)}/{self.MARKET_DATA_BUDGET_MAX_REQUESTS}; retry in ~{retry_in}s.")
                        self._write_shared_state(handle, state)
                        return False
                    state["requests"].append(now)
                    state["last_request_at"] = now
                    self._write_shared_state(handle, state)
                    setattr(self, last_request_attr, now)
                    return True
            time.sleep(sleep_for)

    def get_candles(self, params):
        candle_remaining = self._shared_candle_cooldown_remaining()
        if candle_remaining > 0:
            print(f"[CANDLE RATE LIMIT] Endpoint cooldown active — skipping candle request ({int(candle_remaining)}s remaining).")
            return None
        if not self._reserve_market_data_request("_last_candle_request", self.CANDLE_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.getCandleData, params, endpoint="candle")

    def get_ltp(self, exchange, symbol, token):
        if not self._reserve_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.ltpData, exchange, symbol, token, endpoint="market_data")

    def get_rms_limit(self):
        return self._retry(self.api.rmsLimit, endpoint="rms")

    def get_market_data(self, mode, exchange_tokens):
        if not self._reserve_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.getMarketData, mode, exchange_tokens, endpoint="market_data")
