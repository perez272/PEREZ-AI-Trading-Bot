import time


class AngelClient:
    # Keep historical-candle traffic conservative. A single scan can contain
    # several symbols, so pacing is deliberately slower than the old client.
    CANDLE_REQUEST_INTERVAL = 3.0
    MARKET_DATA_REQUEST_INTERVAL = 2.0

    # After Angel One explicitly rate-limits us, do not send another request
    # until this cooldown expires. This prevents a 10-symbol scan from turning
    # one rejection into ten consecutive rejected requests.
    RATE_LIMIT_BACKOFF = 30
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

    def get_candles(self, params):
        if self._rate_limited_now():
            self._retry(lambda: None)
            return None
        elapsed = time.monotonic() - self._last_candle_request
        wait = self.CANDLE_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_candle_request = time.monotonic()
        return self._retry(self.api.getCandleData, params)

    def get_ltp(self, exchange, symbol, token):
        if self._rate_limited_now():
            self._retry(lambda: None)
            return None
        elapsed = time.monotonic() - self._last_market_data_request
        wait = self.MARKET_DATA_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_market_data_request = time.monotonic()
        return self._retry(self.api.ltpData, exchange, symbol, token)

    def get_rms_limit(self):
        return self._retry(self.api.rmsLimit)

    def get_market_data(self, mode, exchange_tokens):
        if self._rate_limited_now():
            self._retry(lambda: None)
            return None
        elapsed = time.monotonic() - self._last_market_data_request
        wait = self.MARKET_DATA_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_market_data_request = time.monotonic()
        return self._retry(self.api.getMarketData, mode, exchange_tokens)
