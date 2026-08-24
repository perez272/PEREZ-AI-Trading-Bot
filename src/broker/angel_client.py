from datetime import datetime, timezone
import json
import os
import time
from contextlib import contextmanager
from threading import Lock

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


from src.market_data_integrity import validate_candle_sources

class AngelClient:
    CANDLE_REQUEST_INTERVAL = 3.0
    MARKET_DATA_REQUEST_INTERVAL = 3.0
    MARKET_DATA_BUDGET_WINDOW = 60.0
    MARKET_DATA_BUDGET_MAX_REQUESTS = 12
    MARKET_DATA_BUDGET_FILE = "/tmp/perez_ai_market_data_budget.json"
    _GLOBAL_MARKET_DATA_LOCK = Lock()
    RATE_LIMIT_COOLDOWN = 90.0

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

    def _read_shared_state(self, handle):
        handle.seek(0)
        raw = handle.read().strip()
        if not raw:
            return {"requests": [], "cooldown_until": 0.0}
        try:
            state = json.loads(raw)
            return {
                "requests": [float(x) for x in state.get("requests", [])],
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
            return max(0.0, state["cooldown_until"] - now)

    def _set_rate_limit_cooldown(self):
        now = time.monotonic()
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            state["cooldown_until"] = max(
                state["cooldown_until"], now + self.RATE_LIMIT_COOLDOWN
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
            "invalid token" in text or "ag8001" in text or "jwt" in text
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
            "access rate" in text or "rate limit" in text
            or "too many requests" in text or "ab1021" in text
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
        if self._shared_cooldown_remaining() > 0:
            remaining = int(self._shared_cooldown_remaining())
            print(f"[API RATE LIMIT] Global cooldown active — skipping request ({remaining}s remaining).")
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

    def _reserve_market_data_request(self, last_request_attr, interval):
        now = time.monotonic()
        last_request = getattr(self, last_request_attr)
        local_remaining = interval - (now - last_request)
        if local_remaining > 0:
            print(f"[MARKET DATA PACE] Request skipped — {local_remaining:.1f}s until next permitted request.")
            return False
        with self._budget_file_lock() as handle:
            state = self._read_shared_state(handle)
            cooldown_remaining = max(0.0, state["cooldown_until"] - now)
            if cooldown_remaining > 0:
                print(f"[API RATE LIMIT] Global cooldown active — skipping request ({int(cooldown_remaining)}s remaining).")
                self._write_shared_state(handle, state)
                return False
            cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
            requests = [x for x in state["requests"] if x > cutoff]
            state["requests"] = requests
            if len(requests) >= self.MARKET_DATA_BUDGET_MAX_REQUESTS:
                retry_in = max(0, int(self.MARKET_DATA_BUDGET_WINDOW - (now - requests[0])))
                print(
                    "[MARKET DATA BUDGET] Global request budget exhausted — "
                    f"{len(requests)}/{self.MARKET_DATA_BUDGET_MAX_REQUESTS} requests in "
                    f"{self.MARKET_DATA_BUDGET_WINDOW:.0f}s; retry in ~{retry_in}s."
                )
                self._write_shared_state(handle, state)
                return False
            state["requests"].append(now)
            self._write_shared_state(handle, state)
        setattr(self, last_request_attr, now)
        return True

    @staticmethod
    def _symbol_from_token(token):
        """Resolve an Angel instrument token to a symbol for FYERS fallback."""
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "instruments.json")
        path = os.path.abspath(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                instruments = json.load(handle)
            target = str(token).strip()
            for item in instruments:
                if str(item.get("token", "")).strip() == target:
                    return str(item.get("symbol") or item.get("name") or "").strip()
        except Exception:
            pass
        return ""

    def get_candles(self, params):
        """Read Angel + FYERS candles and fail closed on integrity failure."""
        angel_response = None
        fyers_response = None

        if self._reserve_market_data_request(
            "_last_candle_request", self.CANDLE_REQUEST_INTERVAL
        ):
            try:
                response = self._retry(self.api.getCandleData, params)
                if response and isinstance(response, dict) and response.get("status"):
                    angel_response = response
            except Exception as exc:
                print(f"[ANGEL MARKET DATA] Request failed: {exc}")

        try:
            from src.fyers_market_data import get_candles as fyers_get_candles

            exchange = params.get("exchange", "NSE")
            symbol = (
                str(params.get("symbol", "")).strip()
                or self._symbol_from_token(params.get("symboltoken", ""))
            )

            if symbol:
                fyers_response = fyers_get_candles(symbol, exchange)

        except Exception as exc:
            print(f"[FYERS MARKET DATA] Request failed: {exc}")

        def latest_close(response):
            if not isinstance(response, dict):
                return None

            rows = response.get("data")
            if not isinstance(rows, list) or not rows:
                return None

            row = rows[-1]

            if not isinstance(row, (list, tuple)) or len(row) < 5:
                return None

            try:
                return {
                    "price": float(row[4]),
                    "timestamp": row[0],
                }
            except (TypeError, ValueError):
                return None

        angel_quote = latest_close(angel_response)
        fyers_quote = latest_close(fyers_response)

        integrity = validate_candle_sources(
            {
                "ANGEL": angel_quote,
                "FYERS": fyers_quote,
            },
            interval_seconds=300,
            max_age_seconds=600.0,
            max_disagreement_pct=0.50,
            required_sources=("ANGEL", "FYERS"),
        )

        if not integrity.ok:
            print(
                "[MARKET DATA INTEGRITY] FAIL-CLOSED — "
                f"{integrity.reason} | sources={integrity.sources}"
            )
            return None

        angel_response["data_source"] = "ANGEL+FYERS_CORROBORATED"
        angel_response["integrity"] = {
            "ok": True,
            "reason": integrity.reason,
            "sources": integrity.sources,
            "reference_price": integrity.price,
        }

        return angel_response

    def get_ltp(self, exchange, symbol, token):
        if not self._reserve_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.ltpData, exchange, symbol, token)

    def get_rms_limit(self):
        return self._retry(self.api.rmsLimit)

    def get_market_data(self, mode, exchange_tokens):
        if not self._reserve_market_data_request("_last_market_data_request", self.MARKET_DATA_REQUEST_INTERVAL):
            return None
        return self._retry(self.api.getMarketData, mode, exchange_tokens)
