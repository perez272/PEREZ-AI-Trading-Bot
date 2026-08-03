import os
import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect

load_dotenv()

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

obj = SmartConnect(api_key=API_KEY)

session = obj.generateSession(
    CLIENT_ID,
    PASSWORD,
    pyotp.TOTP(TOTP_SECRET).now()
)

if not session.get("status"):
    print("Login Failed")
    print(session)
    raise SystemExit(1)

print("✅ Login Successful")

print("\nFetching Profile...\n")

profile = obj.getProfile(session["data"]["refreshToken"])

print(profile)
