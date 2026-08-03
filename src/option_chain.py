import json
import os

def load_instruments():
    path = "src/data/instruments.json"

    if not os.path.exists(path):
        path = "data/instruments.json"

    with open(path, "r") as f:
        return json.load(f)


def find_option_contract(symbol, strike, option_type):

    instruments = load_instruments()

    matches = []

    for item in instruments:

        name = item.get("name","")
        symbol_name = item.get("symbol","")

        if symbol.upper() in name.upper() or symbol.upper() in symbol_name.upper():

            if option_type.upper() in symbol_name.upper():

                matches.append(item)

    if not matches:
        return {
            "status": "NOT_FOUND",
            "message": "Option contract not found"
        }

    return {
        "status": "FOUND",
        "count": len(matches),
        "contracts": matches[:5]
    }


if __name__ == "__main__":

    result = find_option_contract(
        "AXISBANK",
        1240,
        "CE"
    )

    print(result)
