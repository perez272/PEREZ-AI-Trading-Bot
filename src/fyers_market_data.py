"""Read-only FYERS market-data fallback for PEREZ AI.

This module is deliberately import-safe: credentials are loaded only when a
fallback request is actually made. It never places orders.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _load_credentials():
    from dotenv import load_dotenv

    load_dotenv(".env.fyers")
    load_dotenv(".env.fyers.token")
    client_id = os.getenv("FYERS_CLIENT_ID", "").strip()
    access_token = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
    if not client_id or not access_token:
        return None
    return client_id, access_token


def _fyers_symbol(symbol, exchange):
    symbol = str(symbol).strip().upper()
    exchange = str(exchange).strip().upper()
    if exchange == "NSE" and symbol == "NIFTY":
        return "NSE:NIFTY50-INDEX"
    if exchange == "NSE" and symbol == "BANKNIFTY":
        return "NSE:NIFTYBANK-INDEX"
    if exchange in {"NSE", "BSE"}:
        return f"{exchange}:{symbol}-EQ"
    return f"NSE:{symbol}-EQ"


def get_candles(symbol, exchange, days=5):
    """Return candles in the Angel-compatible [timestamp,O,H,L,C,V] shape.

    FYERS timestamps are candle-start timestamps. We leave the final
    currently-forming candle intact; PEREZ's existing closed-candle validator
    removes it before indicators/scoring.
    """
    credentials = _load_credentials()
    if credentials is None:
        print("[FYERS FALLBACK] Credentials/token unavailable — skip.")
        return None

    try:
        from fyers_apiv3 import fyersModel

        client_id, access_token = credentials
        client = fyersModel.FyersModel(
            client_id=client_id,
            token=access_token,
            log_path="",
        )
        now = datetime.now(IST)
        start = now - timedelta(days=max(1, int(days)))
        data = {
            "symbol": _fyers_symbol(symbol, exchange),
            "resolution": "5",
            "date_format": "1",
            "range_from": start.strftime("%Y-%m-%d"),
            "range_to": now.strftime("%Y-%m-%d"),
            "cont_flag": "1",
        }
        response = client.history(data=data)
        if not isinstance(response, dict) or response.get("s") != "ok":
            print(f"[FYERS FALLBACK] History unavailable for {symbol}: {response}")
            return None
        candles = response.get("candles")
        if not isinstance(candles, list) or not candles:
            print(f"[FYERS FALLBACK] No candles for {symbol}.")
            return None
        normalized = []
        for row in candles:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                timestamp = float(row[0])
                normalized.append([
                    datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).isoformat(),
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ])
            except (TypeError, ValueError, OverflowError):
                continue
        if not normalized:
            return None
        print(f"[FYERS FALLBACK] {symbol}: {len(normalized)} historical 5m candles received.")
        return {"status": True, "data": normalized, "data_source": "FYERS"}
    except Exception as exc:
        print(f"[FYERS FALLBACK] {symbol} request failed: {exc}")
        return None
