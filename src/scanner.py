from SmartApi import SmartConnect
import pyotp
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET

print("="*50)
print("PEREZ AI SCANNER")
print("="*50)

obj=SmartConnect(api_key=API_KEY)
session=obj.generateSession(CLIENT_ID,PASSWORD,pyotp.TOTP(TOTP_SECRET).now())

if session["status"]:
    print("✅ Login Successful")
else:
    print("❌ Login Failed")
