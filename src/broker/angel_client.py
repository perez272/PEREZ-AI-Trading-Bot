import time
from collections import deque


class AngelClient:
    # Historical candles are refreshed only when the scanner needs a new
    # closed candle. Keep a conservative minimum spacing between all
    # market-data requests as additional protection against broker throttling.
    CANDLE_REQUEST_INTERVAL = 3.0
    MARKET_DATA_REQUEST_INTERVAL = 3.0

    # Global per-client market-data budget. This covers candles, LTP and
    # getMarketData calls, not account/order endpoints. Ten 5-minute candles
    # plus a small allowance for other market-data calls fit comfortably.
    MARKET_DATA_BUDGET_WINDOW = 60.0
    MARKET_DATA_BUDGET_MAX_REQUESTS = 12

    # After Angel One explicitly rate-limits us, do not send another request
    # until this cooldown expires. This prevents a scan from turning one
    # rejection into a burst of rejected requests.
    RATE_LIMIT_BACKOFF = 30
    RATE_LIMIT_COOLDOWN = 90

    def __init__(self, smartapi, session_manager=None):
        self.api = smartapi
        self.session_manager = session_manager
        self._last_candle_request = 0.0
        self._last_market_data_request = 0.0
        self._rate_limit_until = 0.0
        self._market_data_requests = deque()

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

    def _prune_market_data_budget(self, now=None):
        now = time.monotonic() if now is None else now
        cutoff = now - self.MARKET_DATA_BUDGET_WINDOW
        while self._market_data_requests and self._market_data_requests[0] <= cutoff:
            self._market_data_requests.popleft()

    def _market_data_budget_available(self):
        now = time.monotonic()
        self._prune_market_data_budget(now)
        if len(self._market_data_requests) >= self.MARKET_DATA_BUDGET_MAX_REQUESTS:
            oldest = self._market_data_requests[0]
            remaining = max(0, int(self.MARKET_DATA_BUDGET_WINDOW - (now - oldest)))
            print(
                "[MARKET DATA BUDGET] Global request budget exhausted — "
                f"{len(self._market_data_requests)}/{self.MARKET_DATA_BUDGET_MAX_REQUESTS} "
                f"requests in {self.MARKET_DATA_BUDGET_WINDOW:.0f}s; "
                f"retry in ~{remaining}s."
            )
            return False
        return True

    def _record_market_data_request(self):
        now = time.monotonic()
        self._prune_market_data_budget(now)
        self._market_data_requests.append(now)

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
        """Call SmartAPI defensively and never turn rate limits into a crash loop."""
        if self._rate_limited_now():
            remaining = max(0, int(self._rate_limit_until - time.monotonic()))
            print(f"[API RATE LIMIT] Cooldown active — skipping request ({remaining}s remaining).")
            return None

        delay = 4
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
                        f"Backing off {self.RATE_LIMIT_BACKOFF}s and cooling down "
                        f"new requests for {self.RATE_LIMIT_COOLDOWN}s."
                    )
                    time.sleep(self.RATE_LIMIT_BACKOFF)
                    return None

                print(f"[API attempt {attempt + 1}/2] {e}")
                if attempt == 0:
                    time.sleep(delay)

        print("[API] Request failed after retries — skipping.")
        return None

    def _prepare_market_data_request(self, last_request_attr, interval):
        if self._rate_limited_now():
            remaining = max(0, int(self._rate_limit_until - time.monotonic()))
            print(f"[API RATE LIMIT] Cooldown active — skipping request ({remaining}s remaining).")
            return False

        if not self._market_data_budget_available():
            return False

        last_request = getattr(self, last_request_attr)
        elapsed = time.monotonic() - last_request
        wait = interval - elapsed
        if wait > 0:
            time.sleep(wait)

        # Re-check the cooldown/budget after sleeping so a concurrently
        # triggered broker cooldown cannot be bypassed by a queued request.
        if self._rate_limited_now() or not self._market_data_budget_available():
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
