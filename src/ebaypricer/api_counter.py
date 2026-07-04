import json
import os
from datetime import date

from .paths import DATA_DIR

COUNTER_PATH = os.path.join(DATA_DIR, "api_counter.json")

_categories = {
    "ebay_oauth": "eBay OAuth token requests",
    "ebay_trading": "eBay Trading API",
    "ebay_browse": "eBay Browse API",
    "ebay_finances": "eBay Finances API",
    "ebay_marketing": "eBay Marketing API",
    "tcgdex": "TCGdex API (card data)",
    "external": "Other external API calls",
}


def _load() -> dict:
    today = date.today().isoformat()
    try:
        with open(COUNTER_PATH) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"date": today, "counts": {name: 0 for name in _categories}}


def _save(data: dict) -> None:
    with open(COUNTER_PATH, "w") as f:
        json.dump(data, f, indent=2)


def track(category: str) -> None:
    if category not in _categories:
        category = "external"
    data = _load()
    data["counts"][category] = data["counts"].get(category, 0) + 1
    _save(data)


def get_counts() -> dict:
    return _load()


def summary() -> str:
    data = _load()
    lines = [f"API calls for {data['date']}:"]
    total = 0
    for name, label in _categories.items():
        count = data["counts"].get(name, 0)
        if count:
            lines.append(f"  {label}: {count}")
        total += count
    lines.append(f"  Total: {total}")
    return "\n".join(lines)
