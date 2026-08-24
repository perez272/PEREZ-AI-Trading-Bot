import os
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

load_dotenv(".env.fyers")

auth_code = os.getenv("FYERS_AUTH_CODE")
client_id = os.getenv("FYERS_CLIENT_ID")
secret_key = os.getenv("FYERS_SECRET_KEY")
redirect_uri = os.getenv("FYERS_REDIRECT_URI")

if not auth_code:
    raise SystemExit("FYERS_AUTH_CODE is not set")
if not all([client_id, secret_key, redirect_uri]):
    raise SystemExit("Missing FYERS_CLIENT_ID / FYERS_SECRET_KEY / FYERS_REDIRECT_URI")

session = fyersModel.SessionModel(
    client_id=client_id,
    secret_key=secret_key,
    redirect_uri=redirect_uri,
    response_type="code",
    grant_type="authorization_code",
)

session.set_token(auth_code)
response = session.generate_token()

print("=== FYERS TOKEN RESPONSE ===")
print(response)

if response.get("s") != "ok":
    raise SystemExit("FYERS token generation FAILED")

access_token = response["access_token"]

with open(".env.fyers.token", "w") as f:
    f.write(f"FYERS_ACCESS_TOKEN={access_token}\n")

os.chmod(".env.fyers.token", 0o600)

print("=== SUCCESS ===")
print("FYERS access token saved to .env.fyers.token")
