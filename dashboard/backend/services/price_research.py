"""
Shared marketplace price research (Phase 3).

price_active_listings.py and avg_active_price.py did their sold/active-listing
research via the eBay Browse API with a client-credentials token — public
marketplace data, not any user's account. So this runs ONCE PER UNIQUE CARD
across ALL users (not per-user), writes to the shared Postgres tables
(price_snapshots, active_price_snapshots, sold_listings), writes per-owner
listing_positions, then updates every user's own active_listings row for
that card with the derived columns (Recent Sold Avg, Price vs Sold Avg,
Active Avg (Top 5), Price Accuracy, Search Position).

Supersedes scripts/price_active_listings.py + scripts/avg_active_price.py,
which read/wrote an Excel workbook and a local SQLite cache as their
inter-step data channel. The card list here comes from the union of all
users' active_listings.card values in Postgres instead.

A Postgres advisory lock guarantees a single active runner across processes,
same pattern as pipeline_runner.py's legacy pipeline lock (different key).
"""

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from statistics import mean, stdev

import psycopg
import requests
from psycopg.types.json import Json

from ebaypricer.browse_api import (
    OUTLIER_SIGMA,
    parse_active_item,
    parse_item,
    search_active_listings,
    search_sold_listings,
)

from dashboard.backend.config import DATABASE_URL
from dashboard.backend.database import get_db

log = logging.getLogger(__name__)

_RESEARCH_LOCK_KEY = 727002
_LOCAL_GUARD = threading.Lock()

LOOKBACK_DAYS = 30
MAX_SOLD_MATCHES = 10
MAX_REPORTED_POSITION = 50
# Wall-clock budget for one run. Each card's API calls are individually bounded
# (requests timeout=15s, capped 429 retries in browse_api.py), but a long tail of
# slow/rate-limited cards could otherwise hold the advisory lock indefinitely and
# block every future manual/scheduled run. Once exceeded, remaining cards are
# skipped (picked up on the next run) rather than left running unbounded.
MAX_RUN_SECONDS = 45 * 60

GENERIC_TITLE_WORDS = {
    "pokemon", "tcg", "card", "near", "mint", "promo", "holo", "holofoil",
    "english", "japanese", "scarlet", "violet", "black", "star", "sv",
    "nm", "lp", "mp", "swirl", "swsh", "sealed", "lot", "pack", "and",
}


def _candidate_queries(title: str, card: str) -> list[str]:
    queries: list[str] = []
    if card:
        queries.append(" ".join(card.split()[:5]))
    words = (title or "").split()
    if words:
        q = " ".join(words[:5])
        if q not in queries:
            queries.append(q)
        distinct = [w for w in words if w.lower().strip("'()") not in GENERIC_TITLE_WORDS]
        if distinct:
            q2 = " ".join(distinct[:5])
            if q2 not in queries:
                queries.append(q2)
    return queries


def _normalize_item_id(raw_id: str) -> str:
    return raw_id.split("|")[1] if raw_id.startswith("v1|") and len(raw_id.split("|")) > 1 else raw_id


def _parse_iso(v: str | None) -> datetime | None:
    """eBay/parse_item ISO timestamp text -> datetime; None for empty/junk."""
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _try_advisory_lock() -> psycopg.Connection | None:
    """Acquire the cross-process research lock; returns the held connection or None."""
    try:
        conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
        row = conn.execute(f"SELECT pg_try_advisory_lock({_RESEARCH_LOCK_KEY})").fetchone()
        if row and row[0]:
            return conn
        conn.close()
        return None
    except Exception:
        return None


def collect_cards_needing_research(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT card FROM active_listings WHERE card IS NOT NULL AND card <> ''"
    ).fetchall()
    return [r["card"] for r in rows]


def _all_cards_researched_today(conn, cards: list[str], today: date) -> bool:
    if not cards:
        return True
    rows = conn.execute(
        """SELECT card_query FROM price_snapshots WHERE snapshot_date = %s
           INTERSECT
           SELECT card_query FROM active_price_snapshots WHERE snapshot_date = %s""",
        (today, today),
    ).fetchall()
    done = {r["card_query"] for r in rows}
    return set(cards) <= done


def _get_today_price_snapshot(conn, card_query: str, today: date) -> dict | None:
    row = conn.execute(
        "SELECT card_query, snapshot_date, sample_size, avg_price, median_price, "
        "min_price, max_price, std_dev, weighted_avg "
        "FROM price_snapshots WHERE card_query = %s AND snapshot_date = %s",
        (card_query, today),
    ).fetchone()
    return dict(row) if row else None


def _save_price_snapshot(conn, snapshot: dict) -> None:
    conn.execute(
        """INSERT INTO price_snapshots
               (card_query, snapshot_date, sample_size, avg_price, median_price,
                min_price, max_price, std_dev, weighted_avg)
           VALUES
               (%(card_query)s, %(snapshot_date)s, %(sample_size)s, %(avg_price)s, %(median_price)s,
                %(min_price)s, %(max_price)s, %(std_dev)s, %(weighted_avg)s)
           ON CONFLICT (card_query, snapshot_date) DO UPDATE SET
               sample_size = EXCLUDED.sample_size, avg_price = EXCLUDED.avg_price,
               median_price = EXCLUDED.median_price, min_price = EXCLUDED.min_price,
               max_price = EXCLUDED.max_price, std_dev = EXCLUDED.std_dev,
               weighted_avg = EXCLUDED.weighted_avg""",
        snapshot,
    )


def _save_sold_listings(conn, parsed_items: list[dict]) -> None:
    if not parsed_items:
        return
    rows = [
        {
            "item_id": p["item_id"],
            "card_query": p["card_query"],
            "title": p["title"],
            "price": p["price"],
            "currency": p["currency"],
            "condition": p["condition"],
            "listing_type": p["listing_type"],
            "sold_date": _parse_iso(p["sold_date"]),
            "url": p["url"],
            "pulled_at": _parse_iso(p["pulled_at"]),
        }
        for p in parsed_items
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO sold_listings
                   (item_id, card_query, title, price, currency, condition, listing_type, sold_date, url, pulled_at)
               VALUES (%(item_id)s, %(card_query)s, %(title)s, %(price)s, %(currency)s, %(condition)s,
                       %(listing_type)s, %(sold_date)s, %(url)s, %(pulled_at)s)
               ON CONFLICT (item_id) DO NOTHING""",
            rows,
        )


def research_card_sold(card_query: str, today: date) -> dict | None:
    """Sold-comp pricing research for one card (ports price_active_listings.py::fetch_price_for_card)."""
    with get_db() as conn:
        existing = _get_today_price_snapshot(conn, card_query, today)
    if existing:
        return existing

    try:
        items = search_sold_listings(card_query, LOOKBACK_DAYS)
    except requests.HTTPError as e:
        log.error("eBay API error researching sold '%s': %s", card_query, e)
        return None

    items.sort(key=lambda i: i.get("itemEndDate") or i.get("itemCreationDate") or "", reverse=True)
    items = items[:MAX_SOLD_MATCHES]
    parsed_items = [p for p in (parse_item(raw, card_query) for raw in items) if p]

    if parsed_items:
        with get_db(read_only=False) as conn:
            _save_sold_listings(conn, parsed_items)
    time.sleep(1)

    pairs = [(p["price"], p["sold_date"]) for p in parsed_items if p.get("currency") == "USD"]
    if not pairs:
        return None

    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    if len(pairs) >= 4:
        raw_prices = [p for p, _ in pairs]
        m, s = mean(raw_prices), stdev(raw_prices)
        pairs = [(p, d) for p, d in pairs if abs(p - m) <= OUTLIER_SIGMA * s]
    if not pairs:
        return None

    prices = [p for p, _ in pairs]
    weighted_sum = 0.0
    weight_total = 0
    for p, sold_date in pairs:
        w = 2 if sold_date >= recent_cutoff else 1
        weighted_sum += p * w
        weight_total += w

    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 else (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2

    snapshot = {
        "card_query": card_query,
        "snapshot_date": today,
        "sample_size": n,
        "avg_price": round(mean(prices), 2),
        "median_price": round(median, 2),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
        "std_dev": round(stdev(prices), 2) if n > 1 else 0.0,
        "weighted_avg": round(weighted_sum / weight_total, 2),
    }
    with get_db(read_only=False) as conn:
        _save_price_snapshot(conn, snapshot)
    return snapshot


def _get_today_active_snapshot(conn, card_query: str, today: date) -> dict | None:
    row = conn.execute(
        "SELECT card_query, snapshot_date, sample_size, avg_price, min_price, max_price "
        "FROM active_price_snapshots WHERE card_query = %s AND snapshot_date = %s",
        (card_query, today),
    ).fetchone()
    return dict(row) if row else None


def _save_active_snapshot(conn, snapshot: dict) -> None:
    conn.execute(
        """INSERT INTO active_price_snapshots
               (card_query, snapshot_date, sample_size, avg_price, min_price, max_price)
           VALUES (%(card_query)s, %(snapshot_date)s, %(sample_size)s, %(avg_price)s, %(min_price)s, %(max_price)s)
           ON CONFLICT (card_query, snapshot_date) DO UPDATE SET
               sample_size = EXCLUDED.sample_size, avg_price = EXCLUDED.avg_price,
               min_price = EXCLUDED.min_price, max_price = EXCLUDED.max_price""",
        snapshot,
    )


def research_card_active(card_query: str, today: date) -> dict | None:
    """Active-listing pricing research for one card (ports avg_active_price.py::fetch_active_price_for_card)."""
    with get_db() as conn:
        existing = _get_today_active_snapshot(conn, card_query, today)
    if existing:
        return existing

    try:
        items = search_active_listings(card_query)
    except requests.RequestException as e:
        log.error("eBay API error researching active '%s': %s", card_query, e)
        return None

    parsed_items = [p for p in (parse_active_item(raw, card_query) for raw in items) if p]
    time.sleep(0.5)

    prices = [p["price"] for p in parsed_items if p.get("currency") == "USD"]
    if not prices:
        return None

    sorted_prices = sorted(prices)
    top5 = sorted_prices[:5]
    snapshot = {
        "card_query": card_query,
        "snapshot_date": today,
        "sample_size": len(top5),
        "avg_price": round(mean(top5), 2),
        "min_price": round(min(top5), 2),
        "max_price": round(max(top5), 2),
    }
    with get_db(read_only=False) as conn:
        _save_active_snapshot(conn, snapshot)
    return snapshot


def research_card_positions(conn, card_query: str, items: list[dict], today: date) -> None:
    """items: [{"item_id": str, "title": str, "user_id": uuid}, ...] for this card.

    Ports price_active_listings.py::fetch_position_for_item, batched per card: search
    results are memoized per query string within this call so items sharing the same
    candidate query (common - they share a card) don't re-hit the API.
    """
    search_cache: dict[str, list[dict]] = {}

    def _search(query: str) -> list[dict]:
        if query not in search_cache:
            try:
                search_cache[query] = search_active_listings(query, limit=MAX_REPORTED_POSITION)
            except requests.HTTPError as e:
                log.error("eBay API error researching position '%s': %s", query, e)
                search_cache[query] = []
        return search_cache[query]

    to_upsert = []
    for it in items:
        item_id = str(it.get("item_id") or "").strip()
        if not item_id:
            continue
        user_id = it["user_id"]
        title = str(it.get("title") or "").strip()

        existing = conn.execute(
            "SELECT 1 FROM listing_positions WHERE user_id = %s AND item_id = %s AND snapshot_date = %s",
            (user_id, item_id, today),
        ).fetchone()
        if existing:
            continue

        position = None
        search_size = 0
        for query in _candidate_queries(title, card_query):
            results = _search(query)
            search_size = len(results)
            for idx, result in enumerate(results):
                if _normalize_item_id(str(result.get("itemId", "")).strip()) == item_id:
                    position = idx + 1
                    break
            if position is not None:
                break

        reported = min(position, MAX_REPORTED_POSITION) if position else MAX_REPORTED_POSITION
        to_upsert.append((user_id, item_id, today, card_query, reported, search_size))

    if to_upsert:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO listing_positions (user_id, item_id, snapshot_date, card_query, position, search_size)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id, item_id, snapshot_date) DO UPDATE SET
                       card_query = EXCLUDED.card_query, position = EXCLUDED.position,
                       search_size = EXCLUDED.search_size""",
                to_upsert,
            )


def update_active_listing_derived_columns(
    conn, card_query: str, sold_snapshot: dict | None, active_snapshot: dict | None, today: date
) -> int:
    """Apply this card's research to every user's matching active_listings rows in one pass
    (ports price_active_listings.py/avg_active_price.py::write_price_data)."""
    rows = conn.execute(
        "SELECT user_id, item_id, price FROM active_listings WHERE card = %s", (card_query,)
    ).fetchall()
    if not rows:
        return 0

    recent_sold_avg = sold_snapshot["weighted_avg"] if sold_snapshot else None
    recent_sold_count = sold_snapshot["sample_size"] if sold_snapshot else None
    active_avg = active_snapshot["avg_price"] if active_snapshot else None
    last_checked = today if sold_snapshot else None

    updates = []
    for r in rows:
        price = r["price"]
        price_vs_sold_avg = None
        if price is not None and recent_sold_avg is not None:
            price_vs_sold_avg = round(float(price) - float(recent_sold_avg), 2)

        benchmarks = [b for b in (recent_sold_avg, active_avg) if b is not None]
        price_accuracy = None
        if price is not None and benchmarks:
            target = sum(float(b) for b in benchmarks) / len(benchmarks)
            if target != 0:
                price_accuracy = round((float(price) - target) / target, 4)

        updates.append(
            (
                recent_sold_avg, recent_sold_count, last_checked, active_avg,
                price_vs_sold_avg, price_accuracy, r["user_id"], r["item_id"],
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE active_listings
               SET recent_sold_avg = %s, recent_sold_count = %s,
                   last_checked = COALESCE(%s, last_checked), active_avg_top5 = %s,
                   price_vs_sold_avg = %s, price_accuracy = %s
               WHERE user_id = %s AND item_id = %s""",
            updates,
        )
    return len(updates)


JOB_NAME = "shared_price_research"


def _start_job_run(started: datetime) -> int | None:
    """Insert a 'running' row (finished_at NULL) so /pipeline/status can see it in flight."""
    try:
        with get_db(read_only=False) as conn:
            row = conn.execute(
                "INSERT INTO job_runs (job_name, user_id, status, started_at) "
                "VALUES (%s, NULL, 'running', %s) RETURNING id",
                (JOB_NAME, started),
            ).fetchone()
            return row["id"] if row else None
    except Exception as e:
        log.error("Failed to start job_runs row: %s", e)
        return None


def _finish_job_run(job_id: int | None, status: str, detail: dict | None = None) -> None:
    try:
        with get_db(read_only=False) as conn:
            if job_id is not None:
                conn.execute(
                    "UPDATE job_runs SET status = %s, finished_at = %s, detail = %s WHERE id = %s",
                    (status, datetime.now(timezone.utc), Json(detail) if detail is not None else None, job_id),
                )
            else:
                conn.execute(
                    "INSERT INTO job_runs (job_name, user_id, status, started_at, finished_at, detail) "
                    "VALUES (%s, NULL, %s, %s, %s, %s)",
                    (JOB_NAME, status, datetime.now(timezone.utc), datetime.now(timezone.utc),
                     Json(detail) if detail is not None else None),
                )
    except Exception as e:
        log.error("Failed to finish job_runs row: %s", e)


def reconcile_stale_job_runs() -> int:
    """Mark any job_runs row still 'running' as orphaned. Call once at process startup:
    if we're just starting up, nothing from a prior process can legitimately still be
    running (single-instance deployment - see SOFTWARE_PLAN.md risks on multi-replica).
    Otherwise a hung/killed run leaves /pipeline/status showing "running" forever,
    since nothing else ever revisits that row."""
    try:
        with get_db(read_only=False) as conn:
            cur = conn.execute(
                "UPDATE job_runs SET status = 'error', finished_at = %s, "
                "detail = COALESCE(detail, '{}'::jsonb) || %s::jsonb "
                "WHERE status = 'running' AND finished_at IS NULL",
                (
                    datetime.now(timezone.utc),
                    Json({"error": "orphaned - process restarted or crashed mid-run"}),
                ),
            )
            return cur.rowcount
    except Exception as e:
        log.error("Failed to reconcile stale job_runs rows: %s", e)
        return 0


def run_shared_price_research(force: bool = False) -> dict:
    """Entry point: research every card currently listed by any user, update shared
    snapshots + each user's derived active_listings columns. Safe to call repeatedly -
    per-card work is skipped if already done today (unless force=True)."""
    if not _LOCAL_GUARD.acquire(blocking=False):
        return {"status": "skipped", "reason": "research already running locally"}

    lock_conn = _try_advisory_lock()
    if lock_conn is None:
        _LOCAL_GUARD.release()
        return {"status": "skipped", "reason": "another runner is active"}

    started = datetime.now(timezone.utc)
    today = started.date()
    job_id = _start_job_run(started)
    try:
        with get_db() as conn:
            cards = collect_cards_needing_research(conn)

        if not cards:
            _finish_job_run(job_id, "ok", {"cards": 0})
            return {"status": "ok", "cards": 0}

        if not force:
            with get_db() as conn:
                if _all_cards_researched_today(conn, cards, today):
                    detail = {"reason": "already researched today", "cards": len(cards)}
                    _finish_job_run(job_id, "skipped", detail)
                    return {"status": "skipped", **detail}

        found_sold = found_active = errors = 0
        timed_out = False
        for i, card in enumerate(cards):
            if (datetime.now(timezone.utc) - started).total_seconds() > MAX_RUN_SECONDS:
                timed_out = True
                remaining = len(cards) - i
                log.warning(
                    "Price research hit its %ds wall-clock budget with %d/%d cards left - "
                    "stopping, they'll be picked up on the next run",
                    MAX_RUN_SECONDS, remaining, len(cards),
                )
                break
            try:
                sold_snapshot = research_card_sold(card, today)
                if sold_snapshot:
                    found_sold += 1
                active_snapshot = research_card_active(card, today)
                if active_snapshot:
                    found_active += 1

                with get_db() as conn:
                    items = [
                        dict(r)
                        for r in conn.execute(
                            "SELECT item_id, title, user_id FROM active_listings WHERE card = %s",
                            (card,),
                        ).fetchall()
                    ]
                if items:
                    with get_db(read_only=False) as conn:
                        research_card_positions(conn, card, items, today)
                        update_active_listing_derived_columns(conn, card, sold_snapshot, active_snapshot, today)
            except Exception as e:
                errors += 1
                log.error("Research failed for card '%s': %s", card, e)

        summary = {
            "cards": len(cards),
            "sold_found": found_sold,
            "active_found": found_active,
            "errors": errors,
            "timed_out": timed_out,
            "duration_s": round((datetime.now(timezone.utc) - started).total_seconds()),
        }
        _finish_job_run(job_id, "timeout" if timed_out else "ok", summary)
        return {"status": "timeout" if timed_out else "ok", **summary}
    except Exception as e:
        _finish_job_run(job_id, "error", {"error": str(e)[:300]})
        return {"status": "error", "error": str(e)[:300]}
    finally:
        try:
            lock_conn.close()
        except Exception:
            pass
        _LOCAL_GUARD.release()
