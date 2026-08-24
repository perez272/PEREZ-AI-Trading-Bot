import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

# Upstox is a separate market-data provider. Credentials remain environment-only.
UPSTOX_ENABLED = os.getenv("UPSTOX_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
UPSTOX_CLIENT_ID = os.getenv("UPSTOX_CLIENT_ID", "")
UPSTOX_CLIENT_SECRET = os.getenv("UPSTOX_CLIENT_SECRET", "")
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")
UPSTOX_INSTRUMENT_KEYS_JSON = os.getenv("UPSTOX_INSTRUMENT_KEYS_JSON", "{}")
UPSTOX_MAX_PRICE_DEVIATION_PCT = os.getenv("UPSTOX_MAX_PRICE_DEVIATION_PCT", "0.35")

# Telegram settings are environment-only. Never commit bot tokens.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
