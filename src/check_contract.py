"""Contract lookup utility; intentionally side-effect free on import."""

from src.option_chain import load_instruments


def find_contract(token="1138612"):
    """Return the instrument matching ``token`` or ``None``."""
    for item in load_instruments():
        if item.get("token") == token:
            return item
    return None


if __name__ == "__main__":
    print(find_contract())
