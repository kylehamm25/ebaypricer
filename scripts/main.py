"""
Usage:
    python main.py
    python main.py --dry-run     # preview without making changes

Runs append_sold_orders.py, get_active.py, price_active_listings.py,
and auto_boost_promotion.py in sequence. price_active_listings.py
runs at most once per day.

Each run is logged to ebayprice/logs/main.log with timestamps.
"""

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "main.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    return logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Run all daily eBay pipelines")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview auto_boost_promotion without making changes")
    return parser.parse_args()


def run_script(log, script_path: Path, description: str, extra_args: list[str] | None = None) -> int:
    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    log.info("--- %s ---", description)
    log.info("Running: %s", " ".join(str(c) for c in cmd))
    sep = "─" * 50
    print(f"\n{sep}")
    print(f"  {description}")
    print(sep)
    result = subprocess.run(cmd, capture_output=False)
    log.info("Exit code: %s", result.returncode)
    return result.returncode


def main():
    log = setup_logging()
    log.info("=== Pipeline started ===")
    args = parse_args()
    scripts_dir = Path(__file__).parent

    rc = run_script(log, scripts_dir / "append_sold_orders.py", "append_sold_orders.py")
    if rc != 0:
        log.error("append_sold_orders.py failed (exit %s)", rc)
        log.info("=== Pipeline finished with errors ===")
        sys.exit(rc)

    rc = run_script(log, scripts_dir / "get_active.py", "get_active.py")
    if rc != 0:
        log.error("get_active.py failed (exit %s)", rc)
        log.info("=== Pipeline finished with errors ===")
        sys.exit(rc)

    rc = run_script(log, scripts_dir / "price_active_listings.py",
                    "price_active_listings.py")
    if rc != 0:
        log.error("price_active_listings.py failed (exit %s)", rc)
        log.info("=== Pipeline finished with errors ===")
        sys.exit(rc)

    boost_args = ["--dry-run"] if args.dry_run else None
    rc = run_script(log, scripts_dir / "auto_boost_promotion.py",
                    "auto_boost_promotion.py", boost_args)
    if rc != 0:
        log.warning("auto_boost_promotion.py skipped (exit %s)", rc)

    log.info("=== Pipeline finished successfully ===")


if __name__ == "__main__":
    main()
