"""
Per-user eBay data sync (Phase 6).

process_ebay_data(user_id) replaces the Excel workbook pipeline for connected users:
  sold orders   <- GetMyeBaySelling (Trading API) + sell/finances fees/earnings merge
  active listings <- GetMyeBaySelling ActiveList (price/watchers/days listed/condition/
                   shipping charge/estimated fees+net, same logic as scripts/get_active.py;
                   ad_rate/search_position aren't set here - ad_rate needs the
                   sell.marketing OAuth scope, search_position comes from price_research.py)
  inventory value history <- recomputed from active listings

Runs on a background schedule (see start_scheduler) and on demand via POST /ebay/sync.
"""

import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from ebaypricer.cards import enrich_rows
from ebaypricer.finances import fetch_finance_fees, merge_fees_into_rows
from ebaypricer.listing_economics import estimate_fees_and_net, resolve_shipping_charge
from ebaypricer.trading_api import fetch_active_listings, fetch_sold_orders, resolve_condition

from dashboard.backend.config import (
    EBAY_PIPELINE_INTERVAL_HOURS,
    EBAY_PRICE_RESEARCH_INTERVAL_HOURS,
    EBAY_PROMOTION_INTERVAL_HOURS,
    EBAY_SYNC_DAYS,
    EBAY_SYNC_INTERVAL_HOURS,
    EXCEL_PATH,
)
from dashboard.backend.database import get_db
from dashboard.backend.services.ebay_oauth import get_access_token

_SOLD_MAP = {
    "Order ID": "order_id",
    "Item ID": "item_id",
    "Sale Date": "sale_date",
    "Buyer": "buyer",
    "Item Title": "item_title",
    "Quantity": "quantity",
    "Item Price": "item_price",
    "Shipping": "shipping",
    "Order Total": "order_total",
    "Total eBay Fees": "total_fees",
    "Order Earnings": "order_earnings",
    "SKU": "sku",
    "Card": "card",
}

# ad_rate needs the sell.marketing OAuth scope (not requested by default - see
# EBAY_SCOPES) and search_position is written separately by price_research.py, so
# those two keep whatever value they already have rather than getting reset here.
_ACTIVE_MAP = {
    "Title": "title",
    "Card": "card",
    "Condition": "condition",
    "SKU": "sku",
    "Price": "price",
    "Shipping Charge": "shipping_charge",
    "Watchers": "watchers",
    "Days Listed": "days_listed",
    "Start Date": "start_date",
    "Quantity": "quantity",
    "Estimated Fees": "estimated_fees",
    "Estimated Net": "estimated_net",
}

_lock_guard = threading.Lock()
_sync_locks: dict[str, threading.Lock] = {}


def _get_lock(key: str) -> threading.Lock:
    with _lock_guard:
        lock = _sync_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _sync_locks[key] = lock
        return lock


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def _to_date(v):
    v = _clean(v)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v).strip())


def _to_num(v):
    v = _clean(v)
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (ValueError, TypeError):
        return None


def _to_int(v):
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(Decimal(str(v)))
    except (ValueError, TypeError):
        return None


def _upsert_rows(conn, table: str, col_map: dict, key_cols: list[str], rows: list[dict]) -> int:
    if not rows:
        return 0
    all_cols = key_cols + [c for c in col_map.values() if c not in key_cols]
    col_sql = ", ".join(all_cols)
    placeholders = ", ".join("%s" for _ in all_cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in all_cols if c not in key_cols)
    insert_sql = (
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(key_cols)}) DO UPDATE SET {updates}"
    )
    with conn.cursor() as cur:
        cur.executemany(insert_sql, [tuple(item[c] for c in all_cols) for item in rows])
    return len(rows)


def _dedupe(raw_rows: list[dict]) -> list[dict]:
    seen: dict = {}
    deduped = []
    for r in raw_rows:
        key = (r["Item ID"], r.get("Sale Date", ""))
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(r)
        else:
            existing = deduped[seen[key]]
            existing_oid = existing.get("Order ID", "")
            candidate_oid = r.get("Order ID", "")
            if existing_oid.startswith(existing.get("Item ID", "")) and not candidate_oid.startswith(
                r.get("Item ID", "")
            ):
                deduped[seen[key]] = r
    return deduped


def _blank_continuation_rows(rows: list[dict]) -> None:
    """For multi-line orders, only the primary (highest-priced) line carries the
    order-level columns; blank them on continuation lines (matches the workbook)."""
    groups: dict = {}
    for i, r in enumerate(rows):
        groups.setdefault(r["Order ID"], []).append(i)
    for indices in groups.values():
        if len(indices) <= 1:
            continue
        primary = max(indices, key=lambda i: rows[i].get("Item Price") or 0)
        for i in indices:
            if i == primary:
                continue
            for col in ("Shipping", "Order Total", "Total eBay Fees", "Order Earnings"):
                rows[i][col] = None


def _fetch_sold_rows(token: str, start_dt: datetime, now: datetime) -> list[dict]:
    raw_rows = fetch_sold_orders(token, start_dt, now)
    min_date = start_dt.strftime("%Y-%m-%d")
    raw_rows = [r for r in raw_rows if r.get("Sale Date", "") >= min_date]
    raw_rows = _dedupe(raw_rows)
    if not raw_rows:
        return []
    fees_by_order, item_id_index, earnings_by_order, debits = fetch_finance_fees(
        token, start_dt - timedelta(days=15), now
    )
    merge_fees_into_rows(raw_rows, fees_by_order, item_id_index, earnings_by_order, debits)
    _blank_continuation_rows(raw_rows)
    enrich_rows(raw_rows)
    return raw_rows


def _build_sold_db_rows(user_id: str, raw_rows: list[dict]) -> list[dict]:
    rows = []
    for r in raw_rows:
        rows.append(
            {
                "user_id": user_id,
                "order_id": _clean(r.get("Order ID")),
                "item_id": _clean(r.get("Item ID")),
                "sale_date": _to_date(r.get("Sale Date")),
                "buyer": _clean(r.get("Buyer")),
                "item_title": _clean(r.get("Item Title")),
                "quantity": _to_int(r.get("Quantity")),
                "item_price": _to_num(r.get("Item Price")),
                "shipping": _to_num(r.get("Shipping")),
                "order_total": _to_num(r.get("Order Total")),
                "total_fees": _to_num(r.get("Total eBay Fees")),
                "order_earnings": _to_num(r.get("Order Earnings")),
                "sku": _clean(r.get("SKU")),
                "card": _clean(r.get("Card")),
            }
        )
    return rows


def _build_active_db_rows(user_id: str, raw_rows: list[dict]) -> list[dict]:
    rows = []
    for r in raw_rows:
        rows.append(
            {
                "user_id": user_id,
                "item_id": _clean(r.get("Item ID")),
                "title": _clean(r.get("Title")),
                "card": _clean(r.get("Card")),
                "condition": _clean(r.get("Condition")),
                "sku": _clean(r.get("SKU")),
                "price": _to_num(r.get("Price")),
                "shipping_charge": _to_num(r.get("Shipping Charge")),
                "watchers": _to_int(r.get("Watchers")),
                "days_listed": _to_int(r.get("Days Listed")),
                "start_date": _to_date(r.get("Start Date")),
                "quantity": _to_int(r.get("Quantity")),
                "estimated_fees": _to_num(r.get("Estimated Fees")),
                "estimated_net": _to_num(r.get("Estimated Net")),
                # No "last_checked" here on purpose: it means "when pricing research
                # last ran for this card", which is price_research.py's to set. It was
                # previously listed here but _ACTIVE_MAP omits it, so _upsert_rows never
                # wrote it - dead code that read as though it worked.
            }
        )
    return rows


def sync_user_ebay_data(user_id: uuid.UUID) -> dict:
    """Fetch and upsert a user's eBay sold orders + active listings. Idempotent."""
    key = str(user_id)
    lock = _get_lock(key)
    if not lock.acquire(blocking=False):
        return {"status": "running", "error": "sync already in progress"}

    def _set_status(conn, status: str):
        conn.execute(
            "UPDATE ebay_connections SET sync_status = %s WHERE user_id = %s",
            [status, key],
        )

    try:
        token = get_access_token(user_id)
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=EBAY_SYNC_DAYS)

        sold_raw = _fetch_sold_rows(token, start_dt, now)
        active_raw = fetch_active_listings(token)
        for row in active_raw:
            row["Condition"] = resolve_condition(row.get("Title", ""), row["Item ID"], token)
            row["Shipping Charge"] = resolve_shipping_charge(row.get("Shipping Cost"), row.get("Shipping Profile"))
            try:
                price = float(row.get("Price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            row["Estimated Fees"], row["Estimated Net"] = estimate_fees_and_net(price)
        enrich_rows(active_raw, title_key="Title")

        sold_rows = _build_sold_db_rows(key, sold_raw)
        active_rows = _build_active_db_rows(key, active_raw)

        with get_db(read_only=False) as conn:
            count_sold = _upsert_rows(conn, "sold_orders", _SOLD_MAP, ["user_id", "order_id", "item_id"], sold_rows)

            # Remove superseded line-item-order-id rows: when a transaction was fetched
            # without ContainingOrder it got keyed "<itemid>-<lineitem>"; once the real
            # order id is known, the canonical row replaces it and the stale row must go.
            # A stale row is one whose order_id looks like "<itemid>-<lineitem>" while a
            # canonical row for the same item + sale date exists.
            conn.execute(
                """DELETE FROM sold_orders s
                   WHERE s.user_id = %s
                     AND s.order_id LIKE s.item_id || '-%%'
                     AND EXISTS (
                         SELECT 1 FROM sold_orders c
                         WHERE c.user_id = s.user_id AND c.item_id = s.item_id
                           AND c.sale_date = s.sale_date AND c.order_id <> s.order_id
                           AND c.order_id NOT LIKE c.item_id || '-%%'
                     )""",
                [key],
            )

            count_active = _upsert_rows(
                conn, "active_listings", _ACTIVE_MAP, ["user_id", "item_id"], active_rows
            )

            # eBay's response is the full current set of active listings; anything
            # already in Postgres but absent here has sold/ended and must be dropped,
            # or it lingers forever and inflates inventory value. Only prune when eBay
            # actually returned listings, so a transient empty/failed fetch can't wipe
            # the table.
            if active_rows:
                conn.execute(
                    "DELETE FROM active_listings WHERE user_id = %s AND item_id != ALL(%s)",
                    [key, [r["item_id"] for r in active_rows]],
                )

            total = conn.execute(
                "SELECT COALESCE(SUM(price * COALESCE(quantity, 1)), 0) AS v, COUNT(*) AS n "
                "FROM active_listings WHERE user_id = %s AND price IS NOT NULL",
                [key],
            ).fetchone()
            conn.execute(
                """INSERT INTO inventory_value_history (user_id, snapshot_date, total_value, total_listings)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                       total_value = EXCLUDED.total_value,
                       total_listings = EXCLUDED.total_listings""",
                (key, now.date(), total["v"], total["n"]),
            )
            conn.execute(
                "UPDATE ebay_connections SET last_synced_at = %s, sync_status = %s WHERE user_id = %s",
                [now, "ok", key],
            )

        # Refresh suggestions off the snapshots we already have (no eBay calls), so
        # newly-synced listings and the daily days_listed drift are reflected without
        # waiting for the next shared price-research round.
        suggestions = {}
        try:
            from dashboard.backend.services.price_research import recompute_suggestions

            suggestions = recompute_suggestions(user_id=key)
        except Exception as e:
            print(f"[sync] suggestion recompute failed: {e}")

        return {
            "status": "ok",
            "sold_line_items": len(sold_raw),
            "sold_orders_upserted": count_sold,
            "active_listings": count_active,
            "inventory_value": float(total["v"]),
            "inventory_listings": total["n"],
            "suggestions": suggestions,
            "synced_at": now.isoformat(),
        }
    except Exception as e:
        try:
            with get_db(read_only=False) as conn:
                _set_status(conn, f"error: {str(e)[:200]}")
        except Exception:
            pass
        return {"status": "error", "error": str(e)[:300]}
    finally:
        lock.release()


def sync_all_users() -> dict:
    with get_db() as conn:
        user_ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM ebay_connections").fetchall()]
    results = {}
    for uid in user_ids:
        results[str(uid)] = sync_user_ebay_data(uid)
    return results


def has_connections() -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM ebay_connections LIMIT 1").fetchone()
    return row is not None


def default_user_connected(default_user_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM ebay_connections WHERE user_id = %s", [default_user_id]
        ).fetchone()
    return row is not None


def _scheduler_loop() -> None:
    pipeline_interval = EBAY_PIPELINE_INTERVAL_HOURS * 3600
    ebay_interval = EBAY_SYNC_INTERVAL_HOURS * 3600
    promotion_interval = EBAY_PROMOTION_INTERVAL_HOURS * 3600
    research_interval = EBAY_PRICE_RESEARCH_INTERVAL_HOURS * 3600
    next_pipeline = time.monotonic() + pipeline_interval  # first round after one interval
    next_ebay = time.monotonic()  # immediate round for status/token refresh
    next_promotion = time.monotonic() + promotion_interval
    next_research = time.monotonic() + research_interval
    while True:
        now = time.monotonic()
        try:
            if now >= next_pipeline:
                next_pipeline = now + pipeline_interval
                if os.path.exists(EXCEL_PATH):
                    try:
                        from dashboard.backend.services.pipeline_runner import run_pipeline_once

                        run_pipeline_once()
                    except Exception as e:
                        print(f"[scheduler] pipeline round failed: {e}")
                # else: legacy Excel-based pipeline isn't reachable from this environment
                # (e.g. a container without the Google Drive mount) - the per-user OAuth
                # sync below already covers sold orders + active listings without it.
            if now >= next_ebay:
                next_ebay = now + ebay_interval
                sync_all_users()
            if now >= next_promotion:
                next_promotion = now + promotion_interval
                try:
                    from dashboard.backend.services.promotion_boost import run_all_users_promotion_boost

                    run_all_users_promotion_boost()
                except Exception as e:
                    print(f"[scheduler] promotion boost round failed: {e}")
            if now >= next_research:
                next_research = now + research_interval
                try:
                    from dashboard.backend.services.price_research import run_shared_price_research

                    run_shared_price_research()
                except Exception as e:
                    print(f"[scheduler] price research round failed: {e}")
        except Exception as e:
            print(f"[scheduler] sync round failed: {e}")
        time.sleep(60)


def start_scheduler() -> None:
    """Start the background sync loop (runs one round immediately)."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="ebay-sync-scheduler")
    thread.start()
    print(f"[scheduler] started (interval {EBAY_SYNC_INTERVAL_HOURS}h)")
