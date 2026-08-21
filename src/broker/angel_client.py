import time


class AngelClient:

    # Conservative pacing for historical candle requests.
    CANDLE_REQUEST_INTERVAL = 1.2
    MARKET_DATA_REQUEST_INTERVAL = 1.5

    # Do not keep hammering Angel One after an explicit rate-limit response.
    RATE_LIMIT_BACKOFF = 15

    def __init__(self, smartapi, session_manager=None):
        self.api = smartapi
        self.session_manager = session_manager
        self._last_candle_request = 0.0
        self._last_market_data_request = 0.0

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
        """Call SmartAPI defensively without turning rate limits into a crash loop."""
        delay = 4
        token_refresh_attempted = False

        for attempt in range(4):
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
                    # A rate-limit response is a service condition, not a reason
                    # to retry the same request five times. Back off once and let
                    # the scanner skip this symbol. This prevents restart loops.
                    print(
                        f"[API RATE LIMIT] Angel One rejected request "
                        f"(attempt {attempt + 1}/4). Backing off {self.RATE_LIMIT_BACKOFF}s."
                    )
                    time.sleep(self.RATE_LIMIT_BACKOFF)
                    return None

                print(f"[API attempt {attempt + 1}/4] {e}")
                if attempt < 3:
                    time.sleep(delay)
                    delay = min(delay * 2, 16)

        print("[API] Request failed after retries — skipping.")
        return None

    def get_candles(self, params):
        elapsed = time.monotonic() - self._last_candle_request
        wait = self.CANDLE_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_candle_request = time.monotonic()
        return self._retry(self.api.getCandleData, params)

    def get_ltp(self, exchange, symbol, token):
        elapsed = time.monotonic() - self._last_market_data_request
        wait = self.MARKET_DATA_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_market_data_request = time.monotonic()
        return self._retry(self.api.ltpData, exchange, symbol, token)

    def get_rms_limit(self):
        return self._retry(self.api.rmsLimit)

    def get_market_data(self, mode, exchange_tokens):
        elapsed = time.monotonic() - self._last_market_data_request
        wait = self.MARKET_DATA_REQUEST_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_market_data_request = time.monotonic()
        return self._retry(self.api.getMarketData, mode, exchange_tokens)
