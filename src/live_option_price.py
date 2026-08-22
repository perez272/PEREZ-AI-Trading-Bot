import time
from datetime import datetime, timedelta
from src.market_scanner_v3 import get_client

_PRICE_MAX_AGE_SECONDS = 5
_price_cache = {}
_quote_cache = {}


def get_option_ltp(exchange, symbol, token):
    key = (exchange, symbol, str(token))
    now = datetime.now()

    cached = _price_cache.get(key)
    if cached and (now - cached[1]) < timedelta(seconds=_PRICE_MAX_AGE_SECONDS):
        return cached[0]

    try:
        response = get_client().get_ltp(exchange, symbol, token)
        if response and response.get("status") and response.get("data"):
            price = float(response["data"]["ltp"])
            if price > 0:
                _price_cache[key] = (price, now)
                return price
    except Exception as e:
        print("LTP ERROR:", e)
        time.sleep(2)

    return None


def get_option_quote(exchange, symbol, token):
    """Fetch fresh FULL quote evidence for an option and fail closed on stale/missing data."""
    key = (exchange, symbol, str(token))
    now = datetime.now()
    cached = _quote_cache.get(key)
    if cached and (now - cached[1]) < timedelta(seconds=_PRICE_MAX_AGE_SECONDS):
        return cached[0]
    try:
        response = get_client().get_market_data("FULL", {exchange: [str(token)]})
        data = response.get("data", {}) if isinstance(response, dict) else {}
        fetched = data.get("fetched", []) if isinstance(data, dict) else []
        if fetched:
            quote = fetched[0]
            if float(quote.get("ltp", 0) or 0) > 0:
                _quote_cache[key] = (quote, now)
                return quote
    except Exception as e:
        print("FULL QUOTE ERROR:", e)
    return None


def get_option_ltp_batch(exchange, contracts):
    """Fetch multiple option LTPs with one paced FULL market-data request."""
    if not contracts:
        return {}

    from src.market_scanner_v3 import get_client

    tokens = []
    symbols = {}

    for contract in contracts:
        symbol = contract.get("symbol") or contract.get("tradingsymbol")
        token = str(contract.get("token", ""))

        if symbol and token:
            tokens.append(token)
            symbols[token] = symbol

    if not tokens:
        return {}

    try:
        response = get_client().get_market_data(
            "FULL",
            {exchange: tokens},
        )

        data = response.get("data", {}) if isinstance(response, dict) else {}
        fetched = data.get("fetched", []) if isinstance(data, dict) else []

        result = {}

        for quote in fetched:
            token = str(quote.get("symbolToken", ""))
            symbol = quote.get("tradingSymbol") or symbols.get(token)
            ltp = quote.get("ltp")

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
