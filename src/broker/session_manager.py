import time
import pyotp
from SmartApi import SmartConnect

class SessionManager:
    def __init__(self, api_key, client_id, password, totp_secret):
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret

        self.obj = None
        self.login_time = 0

    def login(self):
        self.obj = SmartConnect(api_key=self.api_key)

        session = self.obj.generateSession(
            self.client_id,
            self.password,
            pyotp.TOTP(self.totp_secret).now()
        )

        if not session.get("status"):
            raise RuntimeError("Angel One Login Failed")

        self.login_time = time.time()
        print("✓ Angel One Login Successful")

        return self.obj

    def get_client(self):
        if self.obj is None:
            return self.login()
        return self.obj
