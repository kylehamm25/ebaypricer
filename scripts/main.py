"""
Usage:
    python main.py
    python main.py --dry-run     # preview without making changes

Runs append_sold_orders.py, get_active.py, price_active_listings.py,
and auto_boost_promotion.py in sequence. price_active_listings.py
runs at most once per day.

Logs each run to logs/run.log.
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ebaypricer.api_counter import summary as api_summary

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "run.log"


def log_run(entries: list[dict]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [f"[{timestamp}]"]
    dry_run = " (dry-run)" if any(e.get("dry_run") for e in entries) else ""
    parts.append(f"Pipeline{dry_run}")
    for e in entries:
        status = "OK" if e["rc"] == 0 else f"FAIL({e['rc']})"
        parts.append(f"  {e['name']}: {status}")
    with open(LOG_FILE, "a") as f:
        f.write("\n".join(parts) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Run all daily eBay pipelines")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview auto_boost_promotion without making changes")
    return parser.parse_args()


def main():
    args = parse_args()
    scripts_dir = Path(__file__).parent
    results: list[dict] = []

    for script in ("append_sold_orders.py", "get_active.py"):
        print(f"\n--- {script} ---\n")
        result = subprocess.run(
            [sys.executable, str(scripts_dir / script)],
            capture_output=False,
        )
        results.append({"name": script, "rc": result.returncode})
        if result.returncode != 0:
            print(f"ERROR: {script} failed (exit {result.returncode})")
            log_run(results)
            sys.exit(result.returncode)

    print(f"\n--- price_active_listings.py (once per day) ---\n")
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "price_active_listings.py"), "--once-per-day"],
        capture_output=False,
    )
    results.append({"name": "price_active_listings.py", "rc": result.returncode})
    if result.returncode != 0:
        print(f"ERROR: price_active_listings.py failed (exit {result.returncode})")
        log_run(results)
        sys.exit(result.returncode)

    print(f"\n--- auto_boost_promotion.py ---\n")
    boost_args = [str(scripts_dir / "auto_boost_promotion.py")]
    if args.dry_run:
        boost_args.append("--dry-run")
    result = subprocess.run(
        [sys.executable] + boost_args,
        capture_output=False,
    )
    results.append({"name": "auto_boost_promotion.py", "rc": result.returncode, "dry_run": args.dry_run})
    if result.returncode != 0:
        print(f"WARNING: auto_boost_promotion.py skipped (exit {result.returncode})")

    log_run(results)
    print(f"  {api_summary()}")

if __name__ == "__main__":
    main()
