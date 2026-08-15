import json
import os

def load_instruments():
    path = "src/data/instruments.json"

    if not os.path.exists(path):
        path = "data/instruments.json"

    with open(path, "r") as f:
        return json.load(f)


def find_option_contract(symbol, strike, option_type):
    from datetime import datetime

    instruments = load_instruments()

    symbol = str(symbol).upper().strip()
    option_type = str(option_type).upper().strip()

    if option_type not in ("CE", "PE"):
        return {
            "status": "INVALID",
            "message": "option_type must be CE or PE"
        }

    # Angel One instrument master stores option strikes scaled by 100.
    target_strike = float(strike) * 100.0

    today = datetime.now().date()
    matches = []

    for item in instruments:
        name = str(item.get("name", "")).upper()
        symbol_name = str(item.get("symbol", "")).upper()
        instrument_type = str(item.get("instrumenttype", "")).upper()
        exchange = str(item.get("exch_seg", "")).upper()

        if name != symbol:
            continue

        if instrument_type != "OPTSTK":
            continue

        if exchange != "NFO":
            continue

        if not symbol_name.endswith(option_type):
            continue

        try:
            item_strike = float(item.get("strike", 0))
        except (TypeError, ValueError):
            continue

        if abs(item_strike - target_strike) > 0.01:
            continue

        expiry_text = str(item.get("expiry", "")).strip().upper()

        try:
            expiry_date = datetime.strptime(
                expiry_text,
                "%d%b%Y"
            ).date()
        except ValueError:
            continue

        if expiry_date < today:
            continue

        matches.append((expiry_date, item))

    if not matches:
        return {
            "status": "NOT_FOUND",
            "message": (
                f"No valid future {symbol} {strike} {option_type} "
                "contract found"
            )
        }

    # Choose the nearest valid future expiry.
    matches.sort(key=lambda x: x[0])

    selected = matches[0][1]

    return {
        "status": "FOUND",
        "count": len(matches),
        "contract": selected
    }


if __name__ == "__main__":

    result = find_option_contract(
        "AXISBANK",
        1240,
        "CE"
    )

    print(result)
