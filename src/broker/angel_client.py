import time
from collections import deque
from threading import Lock


class AngelClient:
    # One pacing interval for all market-data endpoints. This is deliberately
    # conservative because Angel One can throttle historical candle traffic.
    CANDLE_REQUEST_INTERVAL = 3.0
    MARKET_DATA_REQUEST_INTERVAL = 3.0

    # Global rolling market-data budget. It is class-wide so multiple
    # AngelClient instances in the same Python process share one allowance.
    MARKET_DATA_BUDGET_WINDOW = 60.0
    MARKET_DATA_BUDGET_MAX_REQUESTS = 12
    _GLOBAL_MARKET_DATA_REQUESTS = deque()
    _GLOBAL_MARKET_DATA_LOCK = Lock()

    # Once Angel explicitly rejects a request for rate, stop all new
    # market-data requests for the cooldown period. Do not sleep inside the
    # request path: the caller can safely finish its scan and retry later.
    RATE_LIMIT_COOLDOWN = 90

    def __init__(self, smartapi, session_manager=None):
        self.api = smartapi
        self.session_manager = session_manager
        self._last_candle_request = 0.0
        self._last_market_data_request = 0.0
        self._rate_limit_until = 0.0

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

    def _rate_limited_now(self):
        return time.monotonic() < self._rate_limit_until

    def _set_rate_limit_cooldown(self):
        self._rate_limit_until = time.monotonic() + self.RATE_LIMIT_COOLDOWN

    @classmethod
    def _prune_global_market_data_budget(cls, now=None):
        now = time.monotonic() if now is None else now
        cutoff = now - cls.MARKET_DATA_BUDGET_WINDOW
        with cls._GLOBAL_MARKET_DATA_LOCK:
            while cls._GLOBAL_MARKET_DATA_REQUESTS and cls._GLOBAL_MARKET_DATA_REQUESTS[0] <= cutoff:
                cls._GLOBAL_MARKET_DATA_REQUESTS.popleft()

    @classmethod
    def _market_data_budget_available(cls):
        now = time.monotonic()
        with cls._GLOBAL_MARKET_DATA_LOCK:
            cutoff = now - cls.MARKET_DATA_BUDGET_WINDOW
            while cls._GLOBAL_MARKET_DATA_REQUESTS and cls._GLOBAL_MARKET_DATA_REQUESTS[0] <= cutoff:
                cls._GLOBAL_MARKET_DATA_REQUESTS.popleft()
            count = len(cls._GLOBAL_MARKET_DATA_REQUESTS)
            if count >= cls.MARKET_DATA_BUDGET_MAX_REQUESTS:
                oldest = cls._GLOBAL_MARKET_DATA_REQUESTS[0]
                remaining = max(0, int(cls.MARKET_DATA_BUDGET_WINDOW - (now - oldest)))
                print(
                    "[MARKET DATA BUDGET] Global request budget exhausted — "
                    f"{count}/{cls.MARKET_DATA_BUDGET_MAX_REQUESTS} requests in "
                    f"{cls.MARKET_DATA_BUDGET_WINDOW:.0f}s; retry in ~{remaining}s."
                )
                return False
            return True

    @classmethod
    def _record_market_data_request(cls):
        now = time.monotonic()
        with cls._GLOBAL_MARKET_DATA_LOCK:
            cutoff = now - cls.MARKET_DATA_BUDGET_WINDOW
            while cls._GLOBAL_MARKET_DATA_REQUESTS and cls._GLOBAL_MARKET_DATA_REQUESTS[0] <= cutoff:
                cls._GLOBAL_MARKET_DATA_REQUESTS.popleft()
            cls._GLOBAL_MARKET_DATA_REQUESTS.append(now)

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
        if self._rate_limited_now():
            remaining = max(0, int(self._rate_limit_until - time.monotonic()))
            print(f"[API RATE LIMIT] Cooldown active — skipping request ({remaining}s remaining).")
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
                        f"Global market-data cooldown active for {self.RATE_LIMIT_COOLDOWN}s."
                    )
                    return None

                print(f"[API attempt {attempt + 1}/2] {e}")
                if attempt == 0:
                    time.sleep(4)

        print("[API] Request failed after retries — skipping.")
        return None

    def _prepare_market_data_request(self, last_request_attr, interval):
        if self._rate_limited_now():
            remaining = max(0, int(self._rate_limit_until - time.monotonic()))
            print(f"[API RATE LIMIT] Cooldown active — skipping request ({remaining}s remaining).")
            return False

        # Do not wait merely to consume the budget. If the request is too soon,
        # skip it; the scanner can use its closed-candle cache until a new
        # bucket actually needs to be fetched.
        last_request = getattr(self, last_request_attr)
        elapsed = time.monotonic() - last_request
        if elapsed < interval:
            print(
                f"[MARKET DATA PACE] Request skipped — "
                f"{interval - elapsed:.1f}s until next permitted request."
            )
            return False

        if not self._market_data_budget_available():
            return False
        if self._rate_limited_now():
            return False

        now = time.monotonic()
        setattr(self, last_request_attr, now)
        self._record_market_data_request()
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
