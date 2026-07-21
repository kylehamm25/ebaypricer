import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

NS = "urn:ebay:apis:eBLBaseComponents"
TRADING_URL = "https://api.ebay.com/ws/api.dll"


def _t(el, tag: str) -> str:
    child = el.find(f"{{{NS}}}{tag}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _f(el, path: str, default: float = 0.0) -> float:
    node = el.find(path)
    if node is not None and node.text:
        try:
            return float(node.text)
        except ValueError:
            return default
    return default


def _build_xml(page: int, start_dt: datetime, end_dt: datetime, access_token: str) -> str:
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str   = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="{NS}">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <SoldList>
    <Include>true</Include>
    <OrderStatusFilter>All</OrderStatusFilter>
    <StartTimeFrom>{start_str}</StartTimeFrom>
    <StartTimeTo>{end_str}</StartTimeTo>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
    <Sort>EndTimeDescending</Sort>
  </SoldList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""


def _trading_headers(access_token: str) -> dict:
    return {
        "X-EBAY-API-CALL-NAME":           "GetMyeBaySelling",
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-APP-NAME":            os.getenv("EBAY_APP_ID", ""),
        "X-EBAY-API-DEV-NAME":            os.getenv("EBAY_DEV_ID", ""),
        "X-EBAY-API-CERT-NAME":           os.getenv("EBAY_SECRET", ""),
        "X-EBAY-API-IAF-TOKEN":           access_token,
        "Content-Type":                   "text/xml",
    }


def _parse_address(addr_el) -> tuple[str, str, str, str]:
    if addr_el is None:
        return "", "", "", ""
    return (
        addr_el.findtext(f"{{{NS}}}CityName") or "",
        addr_el.findtext(f"{{{NS}}}StateOrProvince") or "",
        addr_el.findtext(f"{{{NS}}}PostalCode") or "",
        addr_el.findtext(f"{{{NS}}}Country") or "",
    )


def _build_row(order_id, created, status, buyer, txn_el, subtotal, shipping, order_total) -> dict:
    title   = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}Title") or ""
    sku     = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}SKU") or ""
    item_id = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}ItemID") or ""
    price_el = txn_el.find(f"{{{NS}}}TransactionPrice")
    item_price = float(price_el.text) if price_el is not None and price_el.text else 0.0
    qty_el = txn_el.find(f"{{{NS}}}QuantityPurchased")
    qty = int(qty_el.text) if qty_el is not None and qty_el.text else 1

    return {
        "Order ID":     order_id,
        "Item ID":      item_id,
        "Sale Date":    created,
        "Buyer":        buyer,
        "Item Title":   title,
        "Quantity":     qty,
        "Item Price":   item_price,
        "Shipping":     shipping,
        "Order Total":  order_total,
        "SKU":          sku,
    }


def _parse_order(order_el, rows: list) -> None:
    order_id      = _t(order_el, "OrderID")
    created       = _t(order_el, "CreatedTime")[:10]
    status        = _t(order_el, "OrderStatus")
    buyer         = order_el.findtext(f".//{{{NS}}}BuyerUserID") or ""
    total_el      = order_el.find(f"{{{NS}}}Total")
    order_total   = float(total_el.text) if total_el is not None and total_el.text else 0.0
    currency      = total_el.get("currencyID", "USD") if total_el is not None else "USD"
    subtotal_el   = order_el.find(f"{{{NS}}}Subtotal")
    subtotal      = float(subtotal_el.text) if subtotal_el is not None and subtotal_el.text else 0.0
    tax_el        = order_el.find(f".//{{{NS}}}SalesTax/{{{NS}}}SalesTaxAmount")
    tax           = float(tax_el.text) if tax_el is not None and tax_el.text else 0.0

    shipping = _f(order_el, f".//{{{NS}}}ShippingServiceSelected/{{{NS}}}ShippingServiceCost")
    if shipping == 0.0:
        shipping = _f(order_el, f".//{{{NS}}}ShippingDetails/{{{NS}}}ShippingServiceOptions/{{{NS}}}ShippingServiceCost")
    if shipping == 0.0:
        calc = round(order_total - subtotal - tax, 2)
        if calc > 0:
            shipping = calc

    for txn in order_el.findall(f".//{{{NS}}}Transaction"):
        txn_created = created or _t(txn, "CreatedDate")[:10]
        txn_buyer = buyer or (txn.findtext(f".//{{{NS}}}Buyer/{{{NS}}}UserID") or "")

        rows.append(_build_row(
            order_id=order_id,
            created=txn_created,
            status=status,
            buyer=txn_buyer,
            txn_el=txn,
            subtotal=subtotal,
            shipping=shipping,
            order_total=order_total,
        ))


def _parse_transaction(txn_el, rows: list) -> None:
    containing    = txn_el.find(f"{{{NS}}}ContainingOrder")
    order_id      = (_t(containing, "OrderID") if containing is not None else "") or _t(txn_el, "OrderLineItemID") or _t(txn_el, "TransactionID")
    created       = _t(txn_el, "CreatedDate")[:10]
    status        = txn_el.findtext(f".//{{{NS}}}CheckoutStatus/{{{NS}}}Status") or ""
    buyer         = txn_el.findtext(f".//{{{NS}}}Buyer/{{{NS}}}UserID") or ""
    total_el      = txn_el.find(f"{{{NS}}}TransactionPrice")
    item_price    = float(total_el.text) if total_el is not None and total_el.text else 0.0
    ship_cost_el  = txn_el.find(f".//{{{NS}}}ActualShippingCost")
    shipping      = float(ship_cost_el.text) if ship_cost_el is not None and ship_cost_el.text else 0.0
    if shipping == 0.0:
        shipping = _f(txn_el, f".//{{{NS}}}ShippingDetails/{{{NS}}}ShippingServiceOptions/{{{NS}}}ShippingServiceCost")
    tax_el        = txn_el.find(f".//{{{NS}}}Taxes/{{{NS}}}TotalTaxAmount")
    tax           = float(tax_el.text) if tax_el is not None and tax_el.text else 0.0
    qty_el        = txn_el.find(f"{{{NS}}}QuantityPurchased")
    qty           = int(qty_el.text) if qty_el is not None and qty_el.text else 1
    order_total   = round(item_price * qty + shipping + tax, 2)
    addr_el       = txn_el.find(f".//{{{NS}}}Buyer/{{{NS}}}BuyerInfo/{{{NS}}}ShippingAddress")
    ship_city, ship_state, ship_zip, ship_country = _parse_address(addr_el)

    title  = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}Title") or ""
    sku    = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}SKU") or ""
    item_id = txn_el.findtext(f".//{{{NS}}}Item/{{{NS}}}ItemID") or ""

    rows.append({
        "Order ID":     order_id,
        "Item ID":      item_id,
        "Sale Date":    created,
        "Buyer":        buyer,
        "Item Title":   title,
        "Quantity":     qty,
        "Item Price":   item_price,
        "Shipping":     shipping,
        "Order Total":  order_total,
        "SKU":          sku,
    })


def fetch_sold_orders(access_token: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    headers = _trading_headers(access_token)
    rows = []
    page = 1

    while True:
        resp = requests.post(
            TRADING_URL,
            headers=headers,
            data=_build_xml(page, start_dt, end_dt, access_token),
            timeout=30,
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ack = _t(root, "Ack")

        if ack not in ("Success", "Warning"):
            errors = root.findall(f".//{{{NS}}}ShortMessage")
            long_errors = root.findall(f".//{{{NS}}}LongMessage")
            error_codes = root.findall(f".//{{{NS}}}ErrorCode")
            for code, short, long_ in zip(error_codes, errors, long_errors):
                print(f"eBay error [{code.text}]: {short.text} — {long_.text}")
            if not errors:
                print("Raw response:", resp.text[:2000])
            sys.exit(1)

        orders = root.findall(
            f".//{{{NS}}}SoldList/{{{NS}}}OrderTransactionArray/"
            f"{{{NS}}}OrderTransaction"
        )

        for ot in orders:
            order_el = ot.find(f"{{{NS}}}Order")
            txn_el   = ot.find(f"{{{NS}}}Transaction")

            if order_el is not None:
                _parse_order(order_el, rows)
            elif txn_el is not None:
                _parse_transaction(txn_el, rows)

        total_pages_el = root.find(
            f".//{{{NS}}}SoldList/{{{NS}}}PaginationResult/{{{NS}}}TotalNumberOfPages"
        )
        total_pages = int(total_pages_el.text) if total_pages_el is not None and total_pages_el.text else 1

        if page >= total_pages:
            break
        page += 1

    print(f"  Fetched {len(rows)} sold line items")
    return rows


_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def _parse_iso_duration(duration: str) -> timedelta:
    m = _DURATION_RE.match(duration or "")
    if not m:
        return timedelta()
    parts = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return timedelta(days=parts["days"], hours=parts["hours"],
                      minutes=parts["minutes"], seconds=parts["seconds"])


def _build_active_xml(page: int, access_token: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="{NS}">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
    <Sort>TimeLeft</Sort>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""


def _parse_active_item(item_el, rows: list, now: datetime) -> None:
    item_id = _t(item_el, "ItemID")
    title = _t(item_el, "Title")
    sku = _t(item_el, "SKU")
    link = item_el.findtext(f"{{{NS}}}ListingDetails/{{{NS}}}ViewItemURL") or ""

    price_el = item_el.find(f"{{{NS}}}SellingStatus/{{{NS}}}CurrentPrice")
    current_price = float(price_el.text) if price_el is not None and price_el.text else 0.0

    qty_avail_el = item_el.find(f"{{{NS}}}QuantityAvailable")
    qty_available = int(qty_avail_el.text) if qty_avail_el is not None and qty_avail_el.text else 0

    start_el = item_el.find(f"{{{NS}}}ListingDetails/{{{NS}}}StartTime")
    start_date = ""
    days_listed = 0
    if start_el is not None and start_el.text:
        start_dt = datetime.strptime(start_el.text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        start_date = start_dt.strftime("%Y-%m-%d")
        days_listed = (now - start_dt).days

    watch_el = item_el.find(f"{{{NS}}}WatchCount")
    watch_count = int(watch_el.text) if watch_el is not None and watch_el.text else 0

    shipping_profile_el = item_el.find(
        f"{{{NS}}}SellerProfiles/{{{NS}}}SellerShippingProfile/{{{NS}}}ShippingProfileName"
    )
    shipping_profile = shipping_profile_el.text if shipping_profile_el is not None and shipping_profile_el.text else ""

    rows.append({
        "Item ID":            item_id,
        "Title":              title,
        "SKU":                sku,
        "Link":               link,
        "Price":              current_price,
        "Watchers":           watch_count,
        "Days Listed":        days_listed,
        "Start Date":         start_date,
        "Quantity":           qty_available,
        "Shipping Profile":   shipping_profile,
    })


def _build_item_xml(item_id: str, access_token: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{NS}">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""


def _get_item_condition(item_id: str, access_token: str) -> str:
    headers = _trading_headers(access_token)
    headers["X-EBAY-API-CALL-NAME"] = "GetItem"
    try:
        resp = requests.post(
            TRADING_URL,
            headers=headers,
            data=_build_item_xml(item_id, access_token),
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        root = ET.fromstring(resp.text)
        ack = _t(root, "Ack")
        if ack not in ("Success", "Warning"):
            return ""
        display_el = root.find(f".//{{{NS}}}Item/{{{NS}}}ConditionDisplayName")
        return display_el.text.strip() if display_el is not None and display_el.text else ""
    except Exception:
        pass
    return ""


def fetch_active_listings(access_token: str) -> list[dict]:
    headers = _trading_headers(access_token)
    rows: list[dict] = []
    page = 1
    now = datetime.now(timezone.utc)

    while True:
        resp = requests.post(
            TRADING_URL,
            headers=headers,
            data=_build_active_xml(page, access_token),
            timeout=30,
        )
        resp.raise_for_status()

        with open("active_listing_debug.xml", "w", encoding="utf-8") as f:
            f.write(resp.text)

        root = ET.fromstring(resp.text)
        ack = _t(root, "Ack")

        if ack not in ("Success", "Warning"):
            errors = root.findall(f".//{{{NS}}}ShortMessage")
            long_errors = root.findall(f".//{{{NS}}}LongMessage")
            error_codes = root.findall(f".//{{{NS}}}ErrorCode")
            for code, short, long_ in zip(error_codes, errors, long_errors):
                print(f"eBay error [{code.text}]: {short.text} — {long_.text}")
            if not errors:
                print("Raw response:", resp.text[:2000])
            sys.exit(1)

        items = root.findall(
            f".//{{{NS}}}ActiveList/{{{NS}}}ItemArray/{{{NS}}}Item"
        )
        for item_el in items:
            _parse_active_item(item_el, rows, now)

        total_pages_el = root.find(
            f".//{{{NS}}}ActiveList/{{{NS}}}PaginationResult/{{{NS}}}TotalNumberOfPages"
        )
        total_pages = int(total_pages_el.text) if total_pages_el is not None and total_pages_el.text else 1

        if page >= total_pages:
            break
        page += 1

    return rows
