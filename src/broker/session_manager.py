import time
import pyotp
from SmartApi import SmartConnect


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
        # SmartAPI invokes this hook for authenticated REST calls that receive
        # a TokenException. Keep the refresh path centralized and never create
        # a second SmartConnect object concurrently.
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
        if jwt.lower().startswith("bearer "):
            auth = jwt
        else:
            auth = f"Bearer {jwt}" if jwt else ""
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
