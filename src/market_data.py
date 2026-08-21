"""Import-safe instrument universe helpers."""
from pathlib import Path
import json

DEFAULT_INSTRUMENTS_PATH = Path(__file__).resolve().parent.parent / "data" / "instruments.json"


def load_instruments(path=DEFAULT_INSTRUMENTS_PATH):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Instrument master not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Instrument master must contain a JSON list")
    return data


def filter_fo_instruments(instruments):
    return [item for item in instruments if item.get("exch_seg", "") in ("NFO", "BFO")]


def list_underlyings(instruments):
    return sorted({i.get("name", "") for i in filter_fo_instruments(instruments) if i.get("name")})


def main():
    instruments = load_instruments()
    fo = filter_fo_instruments(instruments)
    symbols = list_underlyings(instruments)
    print("=" * 50)
    print(f"Total F&O Instruments : {len(fo)}")
    print(f"Total Underlyings : {len(symbols)}")
    print("=" * 50)
    for symbol in symbols:
        print(symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
