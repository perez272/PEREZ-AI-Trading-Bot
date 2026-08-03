from datetime import datetime
from src.option_chain import load_instruments


def select_contract(symbol, spot, option_type):

    instruments = load_instruments()

    today = datetime.now()

    candidates = []

    atm = round(spot / 10) * 10

    for item in instruments:

        if item.get("name") != symbol:
            continue

        if item.get("instrumenttype") != "OPTSTK":
            continue

        sym = item.get("symbol", "")

        if option_type not in sym:
            continue

        try:
            expiry = datetime.strptime(
                item["expiry"],
                "%d%b%Y"
            )
        except:
            continue

        if expiry < today:
            continue

        strike = float(item["strike"]) / 100

        difference = abs(strike - atm)

        candidates.append({
            "symbol": sym,
            "token": item["token"],
            "exchange": item["exch_seg"],
            "expiry": item["expiry"],
            "strike": strike,
            "lotsize": item["lotsize"],
            "difference": difference
        })


    if not candidates:
        return {
            "status": "NO CONTRACT"
        }


    candidates.sort(
        key=lambda x: (
            x["difference"],
            datetime.strptime(x["expiry"], "%d%b%Y")
        )
    )

    return candidates[0]


if __name__ == "__main__":

    print(
        select_contract(
            "AXISBANK",
            1235.90,
            "CE"
        )
    )
