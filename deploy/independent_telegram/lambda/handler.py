import json
import os
import time
import urllib.parse
import urllib.request

import boto3

TABLE_NAME = os.environ["STATE_TABLE"]
TELEGRAM_TOKEN_SECRET = os.environ["TELEGRAM_TOKEN_SECRET"]
REMOTE_STATUS_TOKEN = os.getenv("REMOTE_STATUS_TOKEN", "")
HEARTBEAT_TTL = int(os.getenv("HEARTBEAT_TTL_SECONDS", "180"))

table = boto3.resource("dynamodb").Table(TABLE_NAME)
secrets = boto3.client("secretsmanager")


def token():
    value = secrets.get_secret_value(SecretId=TELEGRAM_TOKEN_SECRET)["SecretString"]
    try:
        return json.loads(value)["TELEGRAM_BOT_TOKEN"]
    except (TypeError, json.JSONDecodeError, KeyError):
        return value


def telegram(method, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token()}/{method}", data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode())


def save(kind, payload):
    table.put_item(Item={"id": kind, "updated": int(time.time()), "payload": payload})


def get(kind):
    return table.get_item(Key={"id": kind}).get("Item")


def reply(chat_id, text):
    return telegram("sendMessage", chat_id=str(chat_id), text=text[:4000])


def authorized(event):
    if not REMOTE_STATUS_TOKEN:
        return False
    headers = event.get("headers") or {}
    supplied = headers.get("authorization") or headers.get("Authorization") or ""
    return supplied == f"Bearer {REMOTE_STATUS_TOKEN}"


def handle_update(update):
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip().lower()
    if not chat_id:
        return

    allowed_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if allowed_chat and str(chat_id) != allowed_chat:
        return

    heartbeat = get("heartbeat")
    now = int(time.time())
    online = bool(heartbeat and now - int(heartbeat.get("updated", 0)) <= HEARTBEAT_TTL)

    if text in ("/start", "/help"):
        reply(chat_id, "PEREZ AI independent Telegram service is online.\n\n/status — EC2 status\n/heartbeat — latest heartbeat\n/forecast — latest forecast\n/trades — latest trade status")
    elif text == "/status":
        reply(chat_id, f"PEREZ AI STATUS\n\nEC2: {'ONLINE' if online else 'OFFLINE/STALE'}\nLast heartbeat: {heartbeat.get('updated') if heartbeat else 'none'}")
    elif text == "/heartbeat":
        reply(chat_id, json.dumps(heartbeat.get("payload", {}), indent=2)[:3900] if heartbeat else "No heartbeat received.")
    elif text == "/forecast":
        item = get("forecast")
        if not item:
            reply(chat_id, "No forecast has been published yet.")
        else:
            age = now - int(item.get("updated", 0))
            state = "LIVE" if age <= HEARTBEAT_TTL else "STALE"
            reply(chat_id, f"PEREZ AI FUTURE VALUE\n\nState: {state}\nAge: {age}s\n\n{json.dumps(item.get('payload', {}), indent=2)[:3800]}")
    elif text == "/trades":
        item = get("trade")
        reply(chat_id, json.dumps(item.get("payload", {}), indent=2)[:3900] if item else "No trade status published yet.")


def lambda_handler(event, context):
    path = event.get("rawPath") or event.get("path") or "/"
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode()
    payload = json.loads(body)

    if path.endswith("/state"):
        if not authorized(event):
            return {"statusCode": 401, "body": "unauthorized"}
        kind = payload.get("kind")
        if kind not in {"heartbeat", "forecast", "trade"}:
            return {"statusCode": 400, "body": "invalid state kind"}
        save(kind, payload.get("data", {}))
        return {"statusCode": 200, "body": "ok"}

    if path.endswith("/telegram"):
        handle_update(payload)
        return {"statusCode": 200, "body": "ok"}

    return {"statusCode": 404, "body": "not found"}
