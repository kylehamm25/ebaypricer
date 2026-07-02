"""
Usage:
    python main.py

Runs append_sold_orders.py then get_active.py in sequence.
"""

import subprocess
import sys
from pathlib import Path


def main():
    scripts_dir = Path(__file__).parent 

    for script in ("append_sold_orders.py", "get_active.py"):
        print(f"\n{'='*60}")
        print(f"Running {script}...")
        print(f"{'='*60}\n")
        result = subprocess.run(
            [sys.executable, str(scripts_dir / script)],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"ERROR: {script} failed with exit code {result.returncode}")
            sys.exit(result.returncode)

    print(f"\n{'='*60}")
    print("Both scripts completed successfully.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
