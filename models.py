import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def parse_item(item: dict, card_query: str) -> dict | None:
    try:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        if price <= 0:
            return None

        buying_options = item.get("buyingOptions", [])
        if "FIXED_PRICE" in buying_options:
            listing_type = "BIN"
        elif "AUCTION" in buying_options:
            listing_type = "Auction"
        else:
            listing_type = "Unknown"

        sold_date = item.get("itemEndDate") or item.get("itemCreationDate", "")

        return {
            "item_id":      item.get("itemId", ""),
            "card_query":   card_query,
            "title":        item.get("title", ""),
            "price":        price,
            "currency":     price_info.get("currency", "USD"),
            "condition":    item.get("condition", "UNKNOWN"),
            "listing_type": listing_type,
            "sold_date":    sold_date,
            "url":          item.get("itemWebUrl", ""),
            "pulled_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.debug(f"Skipping item due to parse error: {e}")
        return None
