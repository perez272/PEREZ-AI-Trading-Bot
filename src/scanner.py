"""Minimal Angel One connectivity scanner.

Importing this module is side-effect free. Use ``check_login()`` explicitly
or execute the module directly to perform a broker login check.
"""
from __future__ import annotations

import pyotp
from SmartApi import SmartConnect

from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET


def check_login() -> bool:
    obj = SmartConnect(api_key=API_KEY)
    session = obj.generateSession(CLIENT_ID, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())
    if session.get("status"):
        print("✅ Login Successful")
        return True
    print("❌ Login Failed")
    return False


if __name__ == "__main__":
    print("=" * 50)
    print("PEREZ AI SCANNER")
    print("=" * 50)
    check_login()
