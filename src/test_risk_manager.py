from datetime import datetime
from src.risk_manager import IST, is_entry_window, should_force_exit

morning = datetime(2026, 7, 31, 10, 0, tzinfo=IST)
late = datetime(2026, 7, 31, 15, 10, tzinfo=IST)

assert is_entry_window(morning)
assert not is_entry_window(late)
assert should_force_exit(late)

print("PASS: market-hours and forced-exit safeguards work.")
