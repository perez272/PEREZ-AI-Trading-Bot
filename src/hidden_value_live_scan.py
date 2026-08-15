from src.hidden_value_detector import HiddenValueInput, calculate_hidden_value_score
from src.broker.session_manager import SessionManager
from src.broker.angel_client import AngelClient
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET

# SAFE: scanner only — no order functions
SYMBOLS = {
    "ELCIDINVESTMENTS": ("BSE", "503681"),
}

def run():
    client = AngelClient(
        SessionManager(API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET).get_client()
    )

    print("=" * 70)
    print("PEREZ AI — ELCID LIVE MARKET CHECK")
    print("SAFE MODE: READ ONLY / NO ORDERS")
    print("=" * 70)

    for symbol, (exchange, token) in SYMBOLS.items():
        try:
            response = client.get_ltp(exchange, symbol, token)
            print(f"{symbol}: LTP RESPONSE RECEIVED")
            print(response)

            # Live price is verified separately; fundamental fields remain
            # unavailable until a trusted fundamental-data source is connected.
            test = HiddenValueInput(symbol=symbol)
            result = calculate_hidden_value_score(test)

            print(f"Hidden Value Score: {result['score']}/100")
            print(f"Classification: {result['classification']}")
            print("Orders Enabled: FALSE")

        except Exception as e:
            print(f"{symbol}: DATA ERROR: {e}")

if __name__ == "__main__":
    run()
