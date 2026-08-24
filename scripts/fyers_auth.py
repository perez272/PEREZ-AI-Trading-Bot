import os
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

load_dotenv(".env.fyers")

client_id = os.environ["FYERS_CLIENT_ID"]
secret_key = os.environ["FYERS_SECRET_KEY"]
redirect_uri = os.environ["FYERS_REDIRECT_URI"]

session = fyersModel.SessionModel(
    client_id=client_id,
    secret_key=secret_key,
    redirect_uri=redirect_uri,
    response_type="code",
    grant_type="authorization_code",
    state="PEREZ_AI_AUTH",
)

print(session.generate_authcode())
