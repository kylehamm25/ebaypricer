"""
Usage:
    python main.py
    python main.py --dry-run     # preview without making changes

Runs append_sold_orders.py, get_active.py, price_active_listings.py,
and auto_boost_promotion.py in sequence. price_active_listings.py
runs at most once per day.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Run all daily eBay pipelines")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview auto_boost_promotion without making changes")
    return parser.parse_args()


def main():
    args = parse_args()
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

    print(f"\n--- auto_boost_promotion.py ---\n")
    boost_args = [str(scripts_dir / "auto_boost_promotion.py")]
    if args.dry_run:
        boost_args.append("--dry-run")
    result = subprocess.run(
        [sys.executable] + boost_args,
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"WARNING: auto_boost_promotion.py skipped (exit {result.returncode})")

if __name__ == "__main__":
    main()
