import time
import pyotp
from SmartApi import SmartConnect
from src.broker.angel_client import AngelClient

# Angel currently documents 1 request/sec for live market-data quote and
# 3 request/sec + 150/min for historical candles. The old local 12/min shared
# guard was too conservative for the bot's two paper-only processes and could
# block every scanner request before Angel was contacted. Keep a local safety
# ceiling, but leave enough headroom for the main scanner + observer + Telegram
# process sharing one client code.
AngelClient.MARKET_DATA_BUDGET_MAX_REQUESTS = 60


class SessionManager:
    """Own Angel One authentication and expose one coherent session lifecycle."""

    def __init__(self, api_key, client_id, password, totp_secret):
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret
        self.obj = None
        self.login_time = 0.0
        self._refreshing = False

    def _session_expired(self):
        if self._refreshing:
            return
        try:
            self.refresh()
        except Exception as exc:
            print(f"[AUTH] Automatic session refresh failed: {exc}")

    def login(self):
        if self.obj is None:
            self.obj = SmartConnect(api_key=self.api_key)
            self.obj.setSessionExpiryHook(self._session_expired)
        session = self.obj.generateSession(
            self.client_id,
            self.password,
            pyotp.TOTP(self.totp_secret).now(),
        )
        if not session.get("status"):
            self.obj = None
            raise RuntimeError(f"Angel One Login Failed: {session.get('message') or session.get('errorcode') or 'unknown error'}")
        self.login_time = time.time()
        self.obj.setSessionExpiryHook(self._session_expired)
        print("✓ Angel One Login Successful")
        return self.obj

    def refresh(self):
        """Re-authenticate with a fresh TOTP and return the new client."""
        if self._refreshing:
            return self.obj
        self._refreshing = True
        try:
            self.obj = None
            return self.login()
        finally:
            self._refreshing = False

    def get_client(self):
        if self.obj is None:
            return self.login()
        return self.obj

    def websocket_credentials(self):
        """Return credentials in the exact form required by SmartWebSocketV2."""
        client = self.get_client()
        jwt = str(getattr(client, "access_token", "") or "").strip()
        auth = jwt if jwt.lower().startswith("bearer ") else (f"Bearer {jwt}" if jwt else "")
        feed = str(getattr(client, "feed_token", "") or "").strip()
        client_code = str(getattr(client, "userId", "") or self.client_id).strip()
        if not all((auth, self.api_key, client_code, feed)):
            raise RuntimeError("Angel One websocket credentials are incomplete")
        return {
            "auth_token": auth,
            "api_key": self.api_key,
            "client_code": client_code,
            "feed_token": feed,
        }
