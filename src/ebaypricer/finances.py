import json
from datetime import datetime, timedelta, timezone

import requests

FINANCE_URL = "https://apiz.ebay.com/sell/finances/v1/transaction"


class FinancesApiError(Exception):
    """Finances API returned a non-200.

    Raised rather than exiting. This module is imported by the dashboard's per-user
    sync (dashboard/backend/services/ebay_data.py), and sys.exit raises SystemExit,
    which inherits from BaseException - so it slipped straight past that caller's
    `except Exception` handler, killing the sync WITHOUT ever writing the "error:"
    status row that tells the user why their data stopped updating.

    Mirrors marketing_api.MarketingApiError, which exists for the same reason.
    """


# --- Postage assumed when working out what an order actually earned ----------------
# Neither of the numbers eBay hands us is net of postage: totalFeeBasisAmount is the
# amount fees are charged ON (buyer-paid shipping included), and the Trading API's
# Order Total is what the buyer paid. Either way the LABEL is ours to absorb, and eBay
# never reports what it cost here - so both paths in merge_fees_into_rows subtract the
# estimate below.
#
# Free shipping means the buyer paid nothing and we absorbed the label. In the middle
# band we assume a light-parcel label. Above it, we assume the postage we charged is
# roughly what it cost us, and subtract the buyer-paid amount itself.
#
# NOTE: these do not match the eBay Standard Envelope rates used elsewhere
# (listing_economics.SHIPPING_PRICE_MAP = 0.78, suggested_price.ESE_SHIPPING_RATES =
# 0.78/1.36 and ASSUMED_SHIP_COST = 0.78) - each is exactly $0.04 lower. The reason for
# that offset is not recorded anywhere and has not been verified against a real label
# invoice; treat these as unaudited estimates.
FREE_SHIP_LABEL_COST = 0.74
LIGHT_PARCEL_LABEL_COST = 1.32
LIGHT_PARCEL_SHIPPING_MAX = 5.00


def estimated_label_cost(shipping: float | None) -> float:
    """What the postage on an order cost us, given what the buyer was charged for it.

    Note the band edges: a charge at or below FREE_SHIP_LABEL_COST but above zero is
    taken at face value rather than rounded up to the light-parcel label, which is the
    behaviour this has always had."""
    s = float(shipping or 0.0)
    if s == 0.0:
        return FREE_SHIP_LABEL_COST
    if FREE_SHIP_LABEL_COST < s < LIGHT_PARCEL_SHIPPING_MAX:
        return LIGHT_PARCEL_LABEL_COST
    return s


def fetch_finance_fees(access_token: str, start_dt: datetime, end_dt: datetime, debug: bool = False):
    """
    Returns:
        fees_by_order: {real_order_id: {feeType: amount}}
        item_id_index: {item_id: [(transaction_date_iso, real_order_id), ...]}
        earnings_by_order: {real_order_id: gross proceeds (totalFeeBasisAmount, fees NOT subtracted)}
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
    debits_by_order: dict = {}
    earnings_by_order: dict = {}
    item_id_index: dict = {}
    pending_item_fees: dict = {}
    fee_types: set = set()

    url = FINANCE_URL
    params = {"filter": date_filter, "limit": 200}
    page = 1

    while url:
        resp = requests.get(url, headers=headers, params=params if page == 1 else None, timeout=30)
        if resp.status_code != 200:
            raise FinancesApiError(
                f"Finances API error ({resp.status_code}): {resp.text[:500]}"
            )

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

                try:
                    gross = float(txn.get("totalFeeBasisAmount", {}).get("value", 0.0))
                except (TypeError, ValueError):
                    gross = 0.0
                if gross and order_id:
                    earnings_by_order[order_id] = gross

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

            elif txn.get("bookingEntry") == "DEBIT":
                try:
                    value = abs(float(txn.get("amount", {}).get("value", 0.0)))
                except (TypeError, ValueError):
                    value = 0.0
                refs = txn.get("references", [])
                order_ref = next((r.get("referenceId") for r in refs if r.get("referenceType") == "ORDER_ID"), None)
                if order_ref and value:
                    debits_by_order[order_ref] = debits_by_order.get(order_ref, 0.0) + value

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

    return fees_by_order, item_id_index, earnings_by_order, debits_by_order


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


def merge_fees_into_rows(rows: list[dict], fees_by_order: dict, item_id_index: dict, earnings_by_order: dict | None = None, debits_by_order: dict | None = None) -> None:
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

        gross = round(earnings_by_order.get(real_order_id, 0.0), 2) if earnings_by_order and real_order_id else None

        fees = fees_by_order.get(real_order_id) if real_order_id else None
        total_fees = round(sum(fees.values()), 2) if fees else None

        debit = round(debits_by_order.get(real_order_id, 0.0), 2) if debits_by_order and real_order_id else None

        # Order-level, so it sits on one row of the group - the same reason fees and
        # earnings do. Read it once for the order rather than per row, or the
        # continuation rows would price their postage from a blank.
        shipping = next((r.get("Shipping") for r in group if r.get("Shipping") is not None), 0.0)
        postage = estimated_label_cost(shipping)

        for row in group:
            current_oid = str(row.get("Order ID") or "")
            if (
                real_order_id
                and real_order_id != current_oid
                and current_oid.startswith(str(row.get("Item ID") or ""))
            ):
                row["Order ID"] = real_order_id
            row["Total eBay Fees"] = total_fees
            if gross is not None:
                expenses = (total_fees or 0.0) + (debit or 0.0)
                row["Order Earnings"] = round(gross - expenses - postage, 2)
            else:
                order_total = row.get("Order Total") or 0.0
                if total_fees is not None:
                    expenses = total_fees + (debit or 0.0)
                    row["Order Earnings"] = round(order_total - expenses - postage, 2)
                else:
                    row["Order Earnings"] = None
