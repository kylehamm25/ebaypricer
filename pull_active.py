import requests
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv

load_dotenv()

# Load token from file saved by your OAuth script, or fallback to .env
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

NS = "urn:ebay:apis:eBLBaseComponents"

def build_xml(page: int) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="{NS}">
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>"""

def get_active_listings() -> list[dict]:
    headers = {
        "X-EBAY-API-CALL-NAME":              "GetMyeBaySelling",
        "X-EBAY-API-SITEID":                 "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL":    "967",
        "X-EBAY-API-IAF-TOKEN":              ACCESS_TOKEN,
        "Content-Type":                      "text/xml"
    }

    all_listings = []
    page = 1

    while True:
        r = requests.post(
            "https://api.ebay.com/ws/api.dll",
            headers=headers,
            data=build_xml(page),
            timeout=30
        )
        r.raise_for_status()

        root = ET.fromstring(r.text)

        # Check for API-level errors
        ack = root.findtext(f"{{{NS}}}Ack")
        if ack not in ("Success", "Warning"):
            errors = root.findall(f".//{{{NS}}}ShortMessage")
            for e in errors:
                print("eBay error:", e.text)
            break

        # Parse listings
        items = root.findall(f".//{{{NS}}}ActiveList/{{{NS}}}ItemArray/{{{NS}}}Item")
        for item in items:
            all_listings.append({
                "item_id":    item.findtext(f"{{{NS}}}ItemID"),
                "title":      item.findtext(f"{{{NS}}}Title"),
                "price":      item.findtext(f".//{{{NS}}}CurrentPrice"),
                "quantity":   item.findtext(f"{{{NS}}}QuantityAvailable"),
                "url":        item.findtext(f"{{{NS}}}ListingDetails/{{{NS}}}ViewItemURL"),
            })

        # Check if more pages exist
        total_pages = root.findtext(f".//{{{NS}}}ActiveList/{{{NS}}}PaginationResult/{{{NS}}}TotalNumberOfPages")
        print(f"Page {page}/{total_pages} — {len(items)} listings fetched")

        if total_pages is None or page >= int(total_pages):
            break
        page += 1

    return all_listings


listings = get_active_listings()

print(f"\nTotal active listings: {len(listings)}")
for l in listings:
    print(f"  [{l['item_id']}] {l['title']} — ${l['price']} (qty: {l['quantity']})")