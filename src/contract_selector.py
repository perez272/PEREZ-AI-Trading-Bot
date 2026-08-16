from datetime import datetime
from src.option_chain import load_instruments


def select_contract(symbol, spot, option_type):
    """
    Select the nearest valid NFO option contract.

    Supports:
      - OPTSTK: stock options
      - OPTIDX: index options

    Selection priority:
      1. Correct underlying
      2. NFO
      3. CE/PE
      4. Future expiry
      5. Nearest strike to spot
      6. Nearest expiry
    """

    symbol = str(symbol).upper().strip()
    option_type = str(option_type).upper().strip()

    if option_type not in ("CE", "PE"):
        return {"status": "NO CONTRACT", "reason": "Invalid option type"}

    try:
        spot = float(spot)
    except (TypeError, ValueError):
        return {"status": "NO CONTRACT", "reason": "Invalid spot price"}

    instruments = load_instruments()
    today = datetime.now().date()

    candidates = []

    for item in instruments:
        name = str(item.get("name", "")).upper().strip()
        exchange = str(item.get("exch_seg", "")).upper().strip()
        instrument_type = str(item.get("instrumenttype", "")).upper().strip()
        option_symbol = str(item.get("symbol", "")).upper().strip()

        if name != symbol:
            continue

        if exchange != "NFO":
            continue

        if instrument_type not in ("OPTSTK", "OPTIDX"):
            continue

        if not option_symbol.endswith(option_type):
            continue

        expiry_text = str(item.get("expiry", "")).strip().upper()

        try:
            expiry = datetime.strptime(
                expiry_text,
                "%d%b%Y"
            ).date()
        except (TypeError, ValueError):
            continue

        if expiry < today:
            continue

        try:
            strike = float(item.get("strike", 0)) / 100.0
        except (TypeError, ValueError):
            continue

        if strike <= 0:
            continue

        try:
            lot_size = int(float(item.get("lotsize", 0)))
        except (TypeError, ValueError):
            continue

        if lot_size <= 0:
            continue

        candidates.append({
            "symbol": option_symbol,
            "token": str(item.get("token", "")),
            "exchange": exchange,
            "expiry": expiry_text,
            "strike": strike,
            "lotsize": lot_size,
            "instrumenttype": instrument_type,
            "difference": abs(strike - spot),
        })

    if not candidates:
        return {
            "status": "NO CONTRACT",
            "reason": f"No valid NFO {symbol} {option_type} contracts"
        }

    # Nearest strike first, then nearest expiry.
    candidates.sort(
        key=lambda x: (
            x["difference"],
            datetime.strptime(x["expiry"], "%d%b%Y")
        )
    )

    selected = candidates[0]

    selected["status"] = "FOUND"
    selected["underlying"] = symbol

    return selected


if __name__ == "__main__":
    print("=" * 70)
    print("PEREZ AI — READ-ONLY OPTION CONTRACT TEST")
    print("=" * 70)

    tests = [
        ("NIFTY", 25000, "CE"),
        ("NIFTY", 25000, "PE"),
        ("BANKNIFTY", 57000, "CE"),
        ("BANKNIFTY", 57000, "PE"),
        ("ICICIBANK", 1400, "CE"),
        ("ICICIBANK", 1400, "PE"),
    ]

    for symbol, spot, option_type in tests:
        result = select_contract(symbol, spot, option_type)

        if result.get("status") == "FOUND":
            print(
                f"{symbol:<12} {option_type:<2} "
                f"STRIKE={result['strike']:<10g} "
                f"EXPIRY={result['expiry']:<11} "
                f"LOT={result['lotsize']:<5} "
                f"TYPE={result['instrumenttype']:<7} "
                f"TOKEN={result['token']}"
            )
        else:
            print(
                f"{symbol:<12} {option_type:<2} "
                f"FAILED: {result.get('reason', result)}"
            )

    print("=" * 70)
    print("READ-ONLY TEST COMPLETE — NO ORDERS")
    print("=" * 70)
