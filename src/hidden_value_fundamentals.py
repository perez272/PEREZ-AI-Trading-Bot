"""Legacy compatibility wrapper for the canonical hidden-value pipeline.

The old fundamentals module used to own ``data/hidden_value_candidates.csv``.
That made it possible for an empty/header-only legacy run to overwrite the
canonical normalized universe. Candidate generation now belongs exclusively to
``src.hidden_value_data_pipeline``.
"""
from pathlib import Path

OUT = Path("data/hidden_value_candidates.csv")
SOURCE = Path("data/hidden_value_source.csv")


def main():
    print("=" * 65)
    print("PEREZ AI — HIDDEN VALUE FUNDAMENTALS PIPELINE")
    print("=" * 65)
    print(f"Canonical candidates : {OUT}")
    print(f"Source data          : {SOURCE}")
    print("Mode                 : READ ONLY")
    print("Orders               : FALSE")
    print("Status               : USE src.hidden_value_data_pipeline FOR REFRESH")
    print("No candidate file was modified by this compatibility command.")
    print("=" * 65)


if __name__ == "__main__":
    main()
