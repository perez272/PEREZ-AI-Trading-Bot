import time
from datetime import datetime, timedelta

from src.market_scanner_v3 import get_client
from src.market_data_router import MarketDataRouter

_PRICE_MAX_AGE_SECONDS = 5
_price_cache = {}
_quote_cache = {}
_router = None


def _get_router():
    global _router
    if _router is None:
        _router = MarketDataRouter(get_client())
    return _router


def get_option_ltp(exchange, symbol, token):
    key = (exchange, symbol, str(token))
    now = datetime.now()

    cached = _price_cache.get(key)
    if cached and (now - cached[1]) < timedelta(seconds=_PRICE_MAX_AGE_SECONDS):
        return cached[0]

    try:
        price, source = _get_router().get_option_ltp(exchange, symbol, str(token))
        if price is not None and float(price) > 0:
            _price_cache[key] = (float(price), now)
            return float(price)
        print(f"LTP unavailable via market-data router: {symbol} source={source}")
    except Exception as e:
        print("LTP ERROR:", e)
        time.sleep(2)

    return None


def get_option_quote(exchange, symbol, token):
    """Fetch fresh FULL quote evidence through the single market-data gateway."""
    key = (exchange, symbol, str(token))
    now = datetime.now()
    cached = _quote_cache.get(key)
    if cached and (now - cached[1]) < timedelta(seconds=_PRICE_MAX_AGE_SECONDS):
        return cached[0]
    try:
        quote, source = _get_router().get_option_quote(exchange, str(token))
        if quote and float(quote.get("ltp", 0) or 0) > 0:
            quote = dict(quote)
            quote["data_source"] = source
            _quote_cache[key] = (quote, now)
            return quote
        print(f"FULL QUOTE unavailable via market-data router: {symbol} source={source}")
    except Exception as e:
        print("FULL QUOTE ERROR:", e)
    return None


def get_option_ltp_batch(exchange, contracts):
    """Fetch option LTPs through the centralized market-data router."""
    if not contracts:
        return {}

    try:
        routed = _get_router().get_option_ltp_batch(exchange, contracts)
        result = {}
        for item in routed:
            symbol = item.get("symbol") or item.get("tradingsymbol") or item.get("contract")
            ltp = item.get("ltp")
            if symbol and ltp is not None:
                try:
                    price = float(ltp)
                    if price > 0:
                        result[symbol] = price
                except (TypeError, ValueError):
                    pass
        return result
    except Exception as exc:
        print(f"[OPTION BATCH] {type(exc).__name__}: {exc}")
        return {}
