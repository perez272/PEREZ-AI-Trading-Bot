import json

with open("data/instruments.json", "r") as f:
    instruments = json.load(f)

fo = []

for item in instruments:
    exch = item.get("exch_seg", "")

    if exch in ("NFO", "BFO"):
        fo.append(item)

print("=" * 50)
print(f"Total F&O Instruments : {len(fo)}")
print("=" * 50)

symbols = sorted({i.get("name", "") for i in fo if i.get("name")})

print(f"Total Underlyings : {len(symbols)}")
print("=" * 50)

for symbol in symbols:
    print(symbol)
