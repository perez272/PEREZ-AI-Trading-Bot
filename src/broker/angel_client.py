import time

class AngelClient:
    def __init__(self, smartapi):
        self.api = smartapi

    def _retry(self, func, *args, **kwargs):
        delay = 2

        for attempt in range(3):
            try:
                return func(*args, **kwargs)

            except Exception as e:
                msg = str(e)

                if "exceeding access rate" in msg.lower():
                    print(f"[Rate Limit] Waiting {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2
                    continue

                print(f"[Attempt {attempt+1}] {msg}")

                if attempt < 2:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise

    def get_candles(self, params):
        return self._retry(self.api.getCandleData, params)

    def get_ltp(self, exchange, symbol, token):
        return self._retry(self.api.ltpData, exchange, symbol, token)
