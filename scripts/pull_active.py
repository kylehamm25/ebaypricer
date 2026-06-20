import base64
import requests
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv, set_key

_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=_env_path)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
EBAY_APP_ID = os.getenv("EBAY_APP_ID")
EBAY_SECRET = os.getenv("EBAY_SECRET")


def refresh_access_token() -> str | None:
    global ACCESS_TOKEN
    if not REFRESH_TOKEN:
        print("No REFRESH_TOKEN in .env — can't auto-refresh.")
        return ACCESS_TOKEN

    basic_auth = base64.b64encode(f"{EBAY_APP_ID}:{EBAY_SECRET}".encode()).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth}",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
        },
        timeout=10,
    )
    if r.status_code != 200:
        print(f"Token refresh failed ({r.status_code}): {r.text}")
        return ACCESS_TOKEN

    data = r.json()
    ACCESS_TOKEN = data["access_token"]
    set_key(_env_path, "ACCESS_TOKEN", ACCESS_TOKEN)
    print("Access token refreshed and saved to .env")
    return ACCESS_TOKEN

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
    retried = False

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
                emsg = e.text or ""
                print("eBay error:", emsg)
            # Auto-refresh on expired token and retry once
            if not retried and any("hard expired" in (e.text or "") for e in errors):
                refresh_access_token()
                headers["X-EBAY-API-IAF-TOKEN"] = ACCESS_TOKEN
                retried = True
                page = 1
                all_listings = []
                continue
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