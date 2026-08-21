"""Explicit Angel One profile helper; importing performs no network I/O."""
import os
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect


def get_profile():
    load_dotenv()
    values = [os.getenv(k) for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET")]
    if not all(values):
        raise RuntimeError("Angel One credentials are not configured")
    api_key, client_id, password, secret = values
    obj = SmartConnect(api_key=api_key)
    session = obj.generateSession(client_id, password, pyotp.TOTP(secret).now())
    if not session.get("status"):
        raise RuntimeError(f"Angel One login failed: {session}")
    return obj.getProfile(session["data"]["refreshToken"])


if __name__ == "__main__":
    print(get_profile())
