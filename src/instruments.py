import json
import requests
from pathlib import Path

URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

def download_instruments():
    print("Downloading Angel One instrument master...")

    response = requests.get(URL, timeout=60)
    response.raise_for_status()

    instruments = response.json()

    Path("data").mkdir(exist_ok=True)

    with open("data/instruments.json", "w") as f:
        json.dump(instruments, f)

    print(f"Downloaded {len(instruments)} instruments.")
    print("Saved to data/instruments.json")

if __name__ == "__main__":
    download_instruments()
