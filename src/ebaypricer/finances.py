import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

FINANCE_URL = "https://apiz.ebay.com/sell/finances/v1/transaction"


def fetch_finance_fees(access_token: str, start_dt: datetime, end_dt: datetime, debug: bool = False):
    """
    Returns:
        fees_by_order: {real_order_id: {feeType: amount}}
        item_id_index: {item_id: [(transaction_date_iso, real_order_id), ...]}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    pad_start = start_dt - timedelta(days=15)
    pad_end = end_dt + timedelta(days=15)
    date_filter = (
        f"transactionDate:[{pad_start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}.."
        f"{pad_end.strftime('%Y-%m-%dT%H:%M:%S.000Z')}]"
    )

    fees_by_order: dict = {}
    item_id_index: dict = {}
    pending_item_fees: dict = {}
    fee_types: set = set()

    url = FINANCE_URL
    params = {"filter": date_filter, "limit": 200}
    page = 1

    while url:
        resp = requests.get(url, headers=headers, params=params if page == 1 else None, timeout=30)
        if resp.status_code != 200:
            print(f"Finances API error ({resp.status_code}): {resp.text[:500]}")
            sys.exit(1)

        data = resp.json()

        if debug and page == 1:
            print("\n--- DEBUG: full Finances API transaction samples ---")
            sale_sample = next((t for t in data.get("transactions", []) if t.get("transactionType") == "SALE"), None)
            other_sample = next((t for t in data.get("transactions", []) if t.get("transactionType") != "SALE"), None)
            print("\n[SALE-type transaction, full]:")
            print(json.dumps(sale_sample, indent=2) if sale_sample else "  (none found on page 1)")
            print("\n[Non-SALE-type transaction, full]:")
            print(json.dumps(other_sample, indent=2) if other_sample else "  (none found on page 1)")
            print("--- end debug ---\n")

        transactions = data.get("transactions", [])

        for txn in transactions:
            tdate = txn.get("transactionDate", "")

            if txn.get("transactionType") == "SALE":
                order_id = txn.get("orderId", "")
                for li in txn.get("orderLineItems", []):
                    iid = li.get("legacyItemId") or li.get("itemId")
                    liid = li.get("lineItemId", "")
                    if not iid and liid:
                        iid = liid
                    if iid and order_id:
                        item_id_index.setdefault(iid, []).append((tdate, order_id))
                    if liid and liid != iid and order_id:
                        item_id_index.setdefault(liid, []).append((tdate, order_id))

                    for fee in li.get("marketplaceFees", []):
                        fee_type = fee.get("feeType", "UNKNOWN_FEE")
                        try:
                            value = abs(float(fee.get("amount", {}).get("value", 0.0)))
                        except (TypeError, ValueError):
                            value = 0.0
                        fee_types.add(fee_type)
                        bucket = fees_by_order.setdefault(order_id, {})
                        bucket[fee_type] = bucket.get(fee_type, 0.0) + value

            elif txn.get("feeType"):
                fee_type = txn.get("feeType", "UNKNOWN_FEE")
                try:
                    value = abs(float(txn.get("amount", {}).get("value", 0.0)))
                except (TypeError, ValueError):
                    value = 0.0
                refs = txn.get("references", [])
                order_ref = next((r.get("referenceId") for r in refs if r.get("referenceType") == "ORDER_ID"), None)
                item_ref = next((r.get("referenceId") for r in refs if r.get("referenceType") == "ITEM_ID"), None)

                fee_types.add(fee_type)
                if order_ref:
                    bucket = fees_by_order.setdefault(order_ref, {})
                    bucket[fee_type] = bucket.get(fee_type, 0.0) + value
                elif item_ref:
                    pending_item_fees.setdefault(item_ref, []).append((fee_type, value, tdate))

        url = data.get("next")
        params = None
        page += 1
        if page > 100:
            print("WARNING: stopped fee pagination after 100 pages — check filter/limit.")
            break

    for item_id, entries in pending_item_fees.items():
        candidates = item_id_index.get(item_id, [])
        if not candidates:
            continue
        for fee_type, value, fee_date in entries:
            real_order_id = _closest_by_date(candidates, fee_date)
            if real_order_id:
                bucket = fees_by_order.setdefault(real_order_id, {})
                bucket[fee_type] = bucket.get(fee_type, 0.0) + value

    return fees_by_order, item_id_index


def _closest_by_date(candidates: list, target_date_str: str):
    if len(candidates) == 1:
        return candidates[0][1]
    try:
        target = datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return candidates[0][1]

    best_id, best_diff = None, None
    for date_str, order_id in candidates:
        try:
            d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        diff = abs((d - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff, best_id = diff, order_id
    return best_id or candidates[0][1]


def merge_fees_into_rows(rows: list[dict], fees_by_order: dict, item_id_index: dict) -> None:
    if not fees_by_order:
        for row in rows:
            row["Total eBay Fees"] = None
            row["Order Earnings"] = None
        return

    groups: dict = {}
    for row in rows:
        groups.setdefault(row["Order ID"], []).append(row)

    for trading_order_id, group in groups.items():
        real_order_id = trading_order_id if trading_order_id in fees_by_order else None

        if real_order_id is None:
            for row in group:
                iid = row.get("Item ID")
                sale_date = row.get("Sale Date")

                if iid and sale_date and iid in item_id_index:
                    candidates = item_id_index[iid]
                    real_order_id = _closest_by_date(candidates, sale_date)
                    if real_order_id:
                        break

                oid = row.get("Order ID", "")
                if "-" in oid and sale_date:
                    liid = oid.split("-", 1)[1]
                    if liid in item_id_index:
                        candidates = item_id_index[liid]
                        real_order_id = _closest_by_date(candidates, sale_date)
                        if real_order_id:
                            break

        fees = fees_by_order.get(real_order_id) if real_order_id else None
        total_fees = round(sum(fees.values()), 2) if fees else None

        deducted = False
        for row in group:
            row["Total eBay Fees"] = total_fees
            order_total = row.get("Order Total") or 0.0
            shipping = row.get("Shipping") or 0.0
            if total_fees is not None:
                earnings = order_total - total_fees
                if shipping == 0.0 and not deducted:
                    earnings -= 0.74
                    deducted = True
                elif 0.74 < shipping < 5.00:
                    earnings -= 1.32
                else:
                    earnings -= shipping
                row["Order Earnings"] = round(earnings, 2)
            else:
                row["Order Earnings"] = None
