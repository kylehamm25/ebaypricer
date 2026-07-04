"""
Usage:
    python main.py

Runs append_sold_orders.py, get_active.py, and price_active_listings.py
in sequence. price_active_listings.py runs at most once per day.
"""

import subprocess
import sys
from pathlib import Path


def main():
    scripts_dir = Path(__file__).parent 

    for script in ("append_sold_orders.py", "get_active.py"):
        print(f"\n--- {script} ---\n")
        result = subprocess.run(
            [sys.executable, str(scripts_dir / script)],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"ERROR: {script} failed (exit {result.returncode})")
            sys.exit(result.returncode)

    print(f"\n--- price_active_listings.py (once per day) ---\n")
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "price_active_listings.py"), "--once-per-day"],
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"ERROR: price_active_listings.py failed (exit {result.returncode})")
        sys.exit(result.returncode)

    print("\nDone.")


if __name__ == "__main__":
    main()
