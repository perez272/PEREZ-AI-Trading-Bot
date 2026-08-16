import time


class AngelClient:

    # Minimum spacing between historical candle requests.
    # This is deliberately conservative to reduce AB1021 bursts.
    CANDLE_REQUEST_INTERVAL = 1.0
    MARKET_DATA_REQUEST_INTERVAL = 1.2

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

    def refresh_session(self):

        if not self.session_manager:
            return False

        print()
        print("[AUTH] Refreshing Angel One session...")

        try:

            self.api = self.session_manager.refresh()

            print("[AUTH] Session refreshed successfully.")

            return True

        except Exception as e:

            print(
                f"[AUTH] Session refresh failed: {e}"
            )

            return False

    def _retry(self, func, *args, **kwargs):

        delay = 8
        token_refresh_attempted = False

        for attempt in range(5):

            try:

                response = func(
                    *args,
                    **kwargs
                )

                if response is None:
                    raise Exception(
                        "Empty API response"
                    )

                # SmartAPI sometimes returns the
                # invalid-token condition as a response
                # rather than throwing an exception.
                if self._is_invalid_token(
                    response=response
                ):

                    if (
                        self.session_manager
                        and not token_refresh_attempted
                    ):

                        token_refresh_attempted = True

                        if self.refresh_session():

                            func = getattr(
                                self.api,
                                getattr(
                                    func,
                                    "__name__",
                                    ""
                                ),
                                func
                            )

                            continue

                    print(
                        "[AUTH] Invalid token and "
                        "session refresh failed."
                    )

                    return None

                return response

            except Exception as e:

                msg = str(e).lower()

                # -----------------------------------------
                # INVALID TOKEN
                # -----------------------------------------

                if self._is_invalid_token(
                    error=e
                ):

                    if (
                        self.session_manager
                        and not token_refresh_attempted
                    ):

                        token_refresh_attempted = True

                        if self.refresh_session():

                            # Rebind API method after refresh
                            method_name = getattr(
                                func,
                                "__name__",
                                None
                            )

                            if method_name:
                                func = getattr(
                                    self.api,
                                    method_name
                                )

                            continue

                    print(
                        "[AUTH] Could not refresh "
                        "Angel One session."
                    )

                    return None

                # -----------------------------------------
                # RATE LIMIT
                # -----------------------------------------

                if (
                    "access rate" in msg
                    or "rate limit" in msg
                    or "too many requests" in msg
                    or "ab1021" in msg
                ):

                    print(
                        f"[API Protection] "
                        f"Waiting {delay}s..."
                    )

                    time.sleep(delay)

                    delay = min(
                        delay + 4,
                        20
                    )

                    continue

                # -----------------------------------------
                # OTHER TRANSIENT ERRORS
                # -----------------------------------------

                print(
                    f"[Attempt {attempt + 1}] {e}"
                )

                if attempt < 4:

                    time.sleep(delay)

                    delay = min(
                        delay + 4,
                        20
                    )

        return None

    def get_candles(self, params):

        # Global pacing for historical candle requests.
        # Prevents the 210-symbol scanner from sending
        # burst requests to Angel One.

        elapsed = time.monotonic() - self._last_candle_request

        wait = (
            self.CANDLE_REQUEST_INTERVAL
            - elapsed
        )

        if wait > 0:
            time.sleep(wait)

        self._last_candle_request = time.monotonic()

        return self._retry(
            self.api.getCandleData,
            params
        )

    def get_ltp(
        self,
        exchange,
        symbol,
        token
    ):

        return self._retry(
            self.api.ltpData,
            exchange,
            symbol,
            token
        )

    def get_rms_limit(self):

        return self._retry(
            self.api.rmsLimit
        )

    def get_market_data(
        self,
        mode,
        exchange_tokens
    ):

        elapsed = time.monotonic() - self._last_market_data_request
        wait = self.MARKET_DATA_REQUEST_INTERVAL - elapsed

        if wait > 0:
            time.sleep(wait)

        self._last_market_data_request = time.monotonic()

        return self._retry(
            self.api.getMarketData,
            mode,
            exchange_tokens
        )
