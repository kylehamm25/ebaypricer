"""
Usage:
    python main.py

Runs append_sold_orders.py, get_active.py and avg_active_price.py in sequence.
avg_active_price.py runs at most once per day.

price_active_listings.py used to run third. It is the Excel path's sold-side
research - a TCGdex market price written to the workbook as "Recent Sold Avg" and
to SQLite as price_snapshots - and the sold side was removed everywhere (see
dashboard/backend/services/price_research.py). Leaving it in the chain would keep
refilling exactly what was taken out.

The pipeline does not change promoted-listing ad rates. It used to end with
auto_boost_promotion.py; that step was removed so an unattended run can never
move ad spend. The script is still there to be run deliberately by hand.

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
    parser.add_argument("--force", action="store_true",
                        help="Force avg_active_price to run even if snapshots exist for today")
    return parser.parse_args()


def run_script(log, script_path: Path, description: str, extra_args: list[str] | None = None) -> int:
    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    log.info("--- %s ---", description)
    log.info("Running: %s", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l.lstrip() for l in result.stdout.splitlines() if l.strip()]
    if lines:
        print(f"\n{description}")
        for line in lines:
            print(f" > {line}")
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

    avg_extra = ["--force"] if args.force else None
    rc = run_script(log, scripts_dir / "avg_active_price.py",
                    "avg_active_price.py", avg_extra)
    if rc != 0:
        log.error("avg_active_price.py failed (exit %s)", rc)
        log.info("=== Pipeline finished with errors ===")
        sys.exit(rc)

    log.info("=== Pipeline finished successfully ===")


if __name__ == "__main__":
    main()
