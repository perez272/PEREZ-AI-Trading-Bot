import time
import pyotp
from SmartApi import SmartConnect


class SessionManager:
    """Create and refresh an Angel One SmartAPI session.

    Credentials may be supplied explicitly (the existing application path) or
    loaded from the environment-backed src.config module for health checks.
    Secrets are never printed or persisted by this class.
    """

    def __init__(self, api_key=None, client_id=None, password=None, totp_secret=None):
        if any(value is None for value in (api_key, client_id, password, totp_secret)):
            from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET

            api_key = API_KEY if api_key is None else api_key
            client_id = CLIENT_ID if client_id is None else client_id
            password = PASSWORD if password is None else password
            totp_secret = TOTP_SECRET if totp_secret is None else totp_secret

        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret

        self.obj = None
        self.login_time = 0

    @classmethod
    def from_env(cls):
        """Build a session manager from the repository's environment config."""
        return cls()

    def _validate_credentials(self):
        missing = []
        for name, value in (
            ("ANGEL_API_KEY", self.api_key),
            ("ANGEL_CLIENT_ID", self.client_id),
            ("ANGEL_PASSWORD", self.password),
            ("ANGEL_TOTP_SECRET", self.totp_secret),
        ):
            if not str(value or "").strip():
                missing.append(name)

        if missing:
            raise RuntimeError(
                "Angel One credentials missing: " + ", ".join(missing)
            )

    def login(self):
        self._validate_credentials()
        self.obj = SmartConnect(api_key=self.api_key)

        session = self.obj.generateSession(
            self.client_id,
            self.password,
            pyotp.TOTP(self.totp_secret).now(),
        )

        if not session.get("status"):
            raise RuntimeError("Angel One Login Failed")

        self.login_time = time.time()
        print("✓ Angel One Login Successful")

        return self.obj

    def refresh(self):
        """Start a fresh SmartAPI session and return the new client."""
        self.obj = None
        self.login_time = 0
        return self.login()

    def get_client(self):
        if self.obj is None:
            return self.login()
        return self.obj
