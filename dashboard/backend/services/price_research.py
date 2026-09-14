"""
Shared marketplace price research (Phase 3).

Runs ONCE PER UNIQUE CARD across ALL users (not per-user), writes to the shared
Postgres tables (price_snapshots, active_price_snapshots, active_market_listings),
writes per-owner listing_positions, then updates every user's own active_listings
row for that card with the derived columns (Active Avg (Top 5), Price Accuracy,
Search Position).

There is NO sold-side research here, deliberately. eBay's Browse API has no real
"sold items" search - it was once called with a soldDate filter that eBay silently
ignores, returning ordinary active listings mislabeled as sold. The replacement was
a TCGdex/TCGPlayer market price stored in `price_snapshots`, which is one current
asking-price point rather than any record of a sale, and it was removed too: it read
as sold data on every screen it reached. Real sold comps need eBay's Marketplace
Insights API (restricted-access, not on this app's scopes). Until that exists, this
module researches active competitor listings only - don't reintroduce a "sold"
number derived from anything else.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from statistics import mean, stdev

import psycopg
import requests
from psycopg.types.json import Json

from ebaypricer.browse_api import OUTLIER_SIGMA, parse_active_item, search_active_listings
from ebaypricer.cards import card_identity
from ebaypricer.comp_filter import filter_comps

from dashboard.backend.config import DATABASE_URL
from dashboard.backend.database import get_db
from dashboard.backend.services.suggested_price import (
    REPRICE_COOLDOWN_DAYS,
    Suggestion as SuggestionResult,
    compute_suggested_price,
    excluded_title_keyword,
)

log = logging.getLogger(__name__)

_RESEARCH_LOCK_KEY = 727002
_LOCAL_GUARD = threading.Lock()

# How many results to ask Browse for when building a comp pool. Comfortably more than
# we expect to keep, because comp_filter discards ~17% of a pool on average and up to
# 80% for reverse-holo cards (whose searches return mostly regular prints) - fetching
# exactly the number we want to keep leaves too little after filtering. This is a
# bigger `limit` on the SAME single call per card, not an extra call; see the
# ebay-api-rate-limits skill on calls-per-card being the thing that matters.
ACTIVE_FETCH_LIMIT = 30
# Upper bound on how many surviving comps feed one snapshot's aggregates. Defensive
# only - the pool can never exceed what we fetched.
MAX_POOL_SIZE = ACTIVE_FETCH_LIMIT
MAX_REPORTED_POSITION = 50
# Wall-clock budget for one run. Each card's API calls are individually bounded
# (requests timeout=15s, capped 429 retries in browse_api.py), but a long tail of
# slow/rate-limited cards could otherwise hold the advisory lock indefinitely and
# block every future manual/scheduled run. Once exceeded, remaining cards are
# skipped (picked up on the next run) rather than left running unbounded.
MAX_RUN_SECONDS = 45 * 60

# Minimum spacing between ANY two Browse calls in this process, enforced globally by
# _pace() rather than as a per-card sleep. The ebay-api-rate-limits skill requires a
# delay on any per-card API loop; it does not require half a second of it, and it does
# not require the delay to be dead time. At 200 cards the old unconditional 0.5s sleep
# was 100s of a run that is otherwise a few minutes of real work.
#
# Global spacing is what makes RESEARCH_WORKERS safe: the workers overlap the part
# that is pure waiting (eBay latency), while the rate eBay actually sees stays capped
# at 1/INTER_CALL_SLEEP. Raise this if 429s appear in the logs - each one costs a 60s
# backoff in browse_api, far worse than the spacing it saves.
INTER_CALL_SLEEP = 0.15

# Cards researched concurrently. Bounded by the database far more tightly than by
# eBay: database.py's pool has 5 connections and each worker holds one for its write
# phase, so this must stay below that with a slot to spare. The advisory-lock
# connection is opened directly, not from the pool, so it doesn't count.
RESEARCH_WORKERS = 4

_PACE_LOCK = threading.Lock()
_last_call_at = 0.0


def _pace() -> None:
    """Block until INTER_CALL_SLEEP has elapsed since the last Browse call anywhere in
    this process. Holds the lock across the sleep on purpose: callers must queue, or
    every worker wakes at once and the spacing means nothing."""
    global _last_call_at
    with _PACE_LOCK:
        wait = INTER_CALL_SLEEP - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()

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
    """eBay/parse_active_item ISO timestamp text -> datetime; None for empty/junk."""
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


# How recently a forced run must have researched a card to leave it alone. force=True
# means "go and look now", but pressing Refresh twice in a few minutes shouldn't spend
# a few hundred Browse calls re-asking eBay a question answered moments ago. Tracked in
# memory rather than in the table because active_price_snapshots is keyed by DATE only,
# so the database cannot tell a snapshot from this minute from one taken at 00:05; a
# restart simply forfeits the memo and the next run does full work.
FORCE_MIN_AGE_SECONDS = 60 * 60
_RESEARCHED_AT: dict[str, float] = {}
_RESEARCHED_LOCK = threading.Lock()


def _forced_recently(card_query: str) -> bool:
    with _RESEARCHED_LOCK:
        at = _RESEARCHED_AT.get(card_query)
    return at is not None and (time.monotonic() - at) < FORCE_MIN_AGE_SECONDS


def _mark_researched(card_query: str) -> None:
    with _RESEARCHED_LOCK:
        _RESEARCHED_AT[card_query] = time.monotonic()


def collect_cards_needing_research(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT card FROM active_listings WHERE card IS NOT NULL AND card <> ''"
    ).fetchall()
    return [r["card"] for r in rows]


def _all_cards_researched_today(conn, cards: list[str], today: date) -> bool:
    if not cards:
        return True
    rows = conn.execute(
        "SELECT card_query FROM active_price_snapshots WHERE snapshot_date = %s",
        (today,),
    ).fetchall()
    done = {r["card_query"] for r in rows}
    return set(cards) <= done


# Postgres hands numerics back as Decimal, while a snapshot computed in this module
# holds plain floats. That difference is invisible until a Decimal reaches
# suggested_price_basis and json.dumps refuses it ("Object of type Decimal is not JSON
# serializable"), which silently cost a suggestion on every card that hit the daily
# snapshot cache. Every snapshot read from the database goes through here, so the model
# and the basis see one shape whatever the source.
_SNAPSHOT_FLOATS = ("avg_price", "min_price", "max_price", "p25_price", "avg_shipping")


def _snapshot_from_row(row) -> dict:
    snap = dict(row)
    for key in _SNAPSHOT_FLOATS:
        if snap.get(key) is not None:
            snap[key] = float(snap[key])
    if snap.get("sample_size") is not None:
        snap["sample_size"] = int(snap["sample_size"])
    return snap


def _get_today_active_snapshot(conn, card_query: str, today: date) -> dict | None:
    try:
        row = conn.execute(
            "SELECT card_query, snapshot_date, sample_size, avg_price, min_price, max_price, "
            "p25_price, avg_shipping "
            "FROM active_price_snapshots WHERE card_query = %s AND snapshot_date = %s",
            (card_query, today),
        ).fetchone()
    except psycopg.errors.UndefinedColumn:
        # Migration 0007 hasn't been run yet - degrade rather than erroring every
        # cache-hit lookup until it is; avg_shipping is simply absent from the result.
        conn.rollback()
        row = conn.execute(
            "SELECT card_query, snapshot_date, sample_size, avg_price, min_price, max_price, p25_price "
            "FROM active_price_snapshots WHERE card_query = %s AND snapshot_date = %s",
            (card_query, today),
        ).fetchone()
    return _snapshot_from_row(row) if row else None


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list. Used for the p25 floor
    anchor: "cheaper than 75% of the market" - competitive without chasing a single
    (possibly junk) cheapest listing. Rank-based, so it holds its meaning now that
    comp_filter makes the surviving pool size vary card to card."""
    if not sorted_values:
        raise ValueError("empty list")
    idx = max(0, min(len(sorted_values) - 1, int(round(pct * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def _own_item_ids(conn) -> set[str]:
    """Every item_id listed by any user, for excluding our own listings from the
    competitor pool. Without this the aggregates include our own price, which for a
    repricing feature is a feedback loop: cut price -> next run reads that lower
    price as a competitor -> pulls the average down -> suggests cutting again."""
    return {
        str(r["item_id"]).strip()
        for r in conn.execute("SELECT item_id FROM active_listings").fetchall()
        if r["item_id"]
    }


def _save_active_listings(conn, parsed_items: list[dict]) -> None:
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
            "url": p["url"],
            "shipping_cost": p.get("shipping_cost"),
            "shipping_cost_type": p.get("shipping_cost_type") or "",
            "pulled_at": _parse_iso(p["pulled_at"]),
        }
        for p in parsed_items
    ]
    rows.sort(key=lambda r: str(r["item_id"]))
    with conn.cursor() as cur:
        try:
            cur.executemany(
                """INSERT INTO active_market_listings
                       (item_id, card_query, title, price, currency, condition, listing_type, url,
                        shipping_cost, shipping_cost_type, pulled_at)
                   VALUES (%(item_id)s, %(card_query)s, %(title)s, %(price)s, %(currency)s, %(condition)s,
                           %(listing_type)s, %(url)s, %(shipping_cost)s, %(shipping_cost_type)s, %(pulled_at)s)
                   ON CONFLICT (item_id) DO UPDATE SET
                       card_query = EXCLUDED.card_query, title = EXCLUDED.title, price = EXCLUDED.price,
                       currency = EXCLUDED.currency, condition = EXCLUDED.condition,
                       listing_type = EXCLUDED.listing_type, url = EXCLUDED.url,
                       shipping_cost = EXCLUDED.shipping_cost, shipping_cost_type = EXCLUDED.shipping_cost_type,
                       pulled_at = EXCLUDED.pulled_at""",
                rows,
            )
        except psycopg.errors.UndefinedColumn:
            # Migration 0006 hasn't been run yet - degrade to the pre-shipping insert
            # rather than failing every card's active research until it is.
            conn.rollback()
            log.warning("active_market_listings.shipping_cost missing - has migration 0006 been run?")
            with conn.cursor() as cur2:
                cur2.executemany(
                    """INSERT INTO active_market_listings
                           (item_id, card_query, title, price, currency, condition, listing_type, url, pulled_at)
                       VALUES (%(item_id)s, %(card_query)s, %(title)s, %(price)s, %(currency)s, %(condition)s,
                               %(listing_type)s, %(url)s, %(pulled_at)s)
                       ON CONFLICT (item_id) DO UPDATE SET
                           card_query = EXCLUDED.card_query, title = EXCLUDED.title, price = EXCLUDED.price,
                           currency = EXCLUDED.currency, condition = EXCLUDED.condition,
                           listing_type = EXCLUDED.listing_type, url = EXCLUDED.url, pulled_at = EXCLUDED.pulled_at""",
                    rows,
                )


_SNAPSHOT_COLUMNS = (
    "card_query", "snapshot_date", "sample_size", "avg_price", "min_price", "max_price", "p25_price"
)
# Columns introduced by later migrations, newest first. Each is dropped from the INSERT
# if the database doesn't have it yet, so a deployment that hasn't pasted a migration
# degrades to storing less rather than failing every card's research. Replaces what had
# become a hand-written fallback branch per migration.
#   avg_shipping  -> 0007
#   pool_quality  -> 0010
_OPTIONAL_SNAPSHOT_COLUMNS = ("pool_quality", "avg_shipping")


def _save_active_snapshot(conn, snapshot: dict) -> None:
    params = dict(snapshot)
    if "pool_quality" in params:
        params["pool_quality"] = Json(params["pool_quality"])

    optional = [c for c in _OPTIONAL_SNAPSHOT_COLUMNS if c in params]
    while True:
        cols = list(_SNAPSHOT_COLUMNS) + optional
        placeholders = ", ".join(f"%({c})s" for c in cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "card_query" and c != "snapshot_date")
        try:
            conn.execute(
                f"""INSERT INTO active_price_snapshots ({", ".join(cols)})
                    VALUES ({placeholders})
                    ON CONFLICT (card_query, snapshot_date) DO UPDATE SET {updates}""",
                params,
            )
            return
        except psycopg.errors.UndefinedColumn:
            conn.rollback()
            if not optional:
                raise
            missing = optional.pop(0)
            log.warning(
                "active_price_snapshots.%s missing - has the migration that adds it been run?",
                missing,
            )


def research_card_active(
    card_query: str, today: date, force: bool = False, own_ids: set[str] | None = None,
) -> dict | None:
    """Active-listing pricing research for one card (ports avg_active_price.py::fetch_active_price_for_card).

    force=True bypasses today's cached snapshot: without it a changed algorithm
    silently has no effect on any card already researched today.

    own_ids is the caller's cached set of our own item_ids. It is the same set for
    every card in a run, so a batch passes it in once instead of re-reading the whole
    active_listings table per card - that was ~200 pointless round trips to a remote
    database. Omitted (None) it reads them itself, which is what the single-card
    refresh path wants."""
    if not force:
        with get_db() as conn:
            existing = _get_today_active_snapshot(conn, card_query, today)
        if existing:
            return existing

    _pace()
    try:
        items = search_active_listings(card_query, limit=ACTIVE_FETCH_LIMIT)
    except requests.RequestException as e:
        log.error("eBay API error researching active '%s': %s", card_query, e)
        return None

    parsed_items = [p for p in (parse_active_item(raw, card_query) for raw in items) if p]

    # Exclude our own listings from the competitor pool. eBay's search returns them
    # like any other result (it is in fact how search_position is derived), so
    # without this every aggregate is partly a measurement of ourselves.
    # active_market_listings.item_id is the raw "v1|123456|0" form while
    # active_listings.item_id is bare numeric, hence _normalize_item_id.
    if own_ids is None:
        with get_db() as conn:
            own_ids = _own_item_ids(conn)
    competitor_items = [
        p for p in parsed_items if _normalize_item_id(str(p.get("item_id") or "").strip()) not in own_ids
    ]
    self_excluded = len(parsed_items) - len(competitor_items)
    # If stripping ourselves leaves too little to reason about, fall back to the
    # unfiltered pool rather than emitting a garbage band off 1-2 comps.
    if len(competitor_items) >= 3:
        parsed_items = competitor_items
    elif self_excluded:
        log.warning(
            "Self-exclusion left only %d comps for '%s'; keeping unfiltered pool",
            len(competitor_items), card_query,
        )

    # Persist the RAW pool (pre comp-filter) - active_market_listings is the record of
    # what Browse actually returned, and keeping the rejects is what makes it possible
    # to audit the filter later and measure a rule change against real history. Only
    # the aggregates below are computed from the filtered pool.
    raw_items = parsed_items

    # Drop results that aren't the card we're pricing: graded slabs, multi-card lots,
    # print-defect one-offs, foreign-market/Japanese prints, and wrong prints. Browse
    # matches words, not identity, so an unfiltered pool for "Charmander 46 Base" ran
    # $0.99-$1500 on a card we list at $5.24. See ebaypricer/comp_filter.py.
    identity = card_identity(card_query)
    parsed_items, pool_quality = filter_comps(parsed_items, identity)
    if pool_quality["dropped"]:
        log.info(
            "Comp filter '%s': kept %d/%d (%s)%s",
            card_query, pool_quality["kept"], pool_quality["in"],
            ", ".join(f"{k}={v}" for k, v in sorted(pool_quality["reasons"].items())),
            " [soft drops restored - pool too thin]" if pool_quality["soft_restored"] else "",
        )

    prices = [p["price"] for p in parsed_items if p.get("currency") == "USD"]
    if not prices:
        # No snapshot to write, but active_market_listings is the record of what Browse
        # returned and must still get the raw pool - this used to be saved before the
        # filter ran, so bailing out here silently stopped recording it.
        if raw_items:
            with get_db(read_only=False) as conn:
                _save_active_listings(conn, raw_items)
        return None

    # Drop outliers (a misclassified/bundle/wrong-print listing miles away from the
    # rest) before averaging, same 2-sigma approach as the rest of this codebase.
    if len(prices) >= 4:
        m, s = mean(prices), stdev(prices)
        if s > 0:
            filtered = [p for p in prices if abs(p - m) <= OUTLIER_SIGMA * s]
            if filtered:
                prices = filtered

    # The whole surviving pool, not a cheapest-N slice. Fetching ACTIVE_FETCH_LIMIT
    # results and then averaging only the cheapest MAX_ACTIVE_MATCHES of them would bias
    # every anchor downward and quietly re-cut every price. Historically these were the
    # same number, so the slice was inert and the aggregate has always meant "mean of
    # the pool" - keep it that way and let comp_filter, not price rank, decide
    # membership. Capped so a pathologically large pool can't skew the run.
    pool = sorted(prices)[:MAX_POOL_SIZE]

    # Mean shipping cost among today's comp pool (a separate descriptive stat, computed
    # over the same filtered items). Feeds compute_suggested_price's total-price
    # positioning: comparing
    # our item price alone against comp item prices makes a $12 free-shipping listing
    # look overpriced next to a $10-item/$5-shipping comp that's actually $3 more
    # expensive landed. None (not 0) when no comp reported a cost, so the model can
    # tell "no data" apart from "comps really do average $0 shipping".
    shipping_costs = [
        p["shipping_cost"] for p in parsed_items
        if p.get("currency") == "USD" and p.get("shipping_cost") is not None
    ]
    avg_shipping = round(mean(shipping_costs), 2) if shipping_costs else None

    snapshot = {
        "card_query": card_query,
        "snapshot_date": today,
        "sample_size": len(pool),
        "avg_price": round(mean(pool), 2),
        "min_price": round(min(pool), 2),
        "max_price": round(max(pool), 2),
        "p25_price": round(_percentile(pool, 0.25), 2),
        "avg_shipping": avg_shipping,
        "pool_quality": pool_quality,
    }
    # Both writes share one checkout from the 5-slot pool. They used to take one
    # each, on either side of the filtering, for no reason - the raw pool is already
    # in hand by then.
    with get_db(read_only=False) as conn:
        if raw_items:
            _save_active_listings(conn, raw_items)
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
            _pace()
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
            # Also mirror today's position onto active_listings.search_position, so it's
            # populated for users on the Excel-free per-user OAuth sync path too (the
            # legacy Excel pipeline previously was the only source of this column).
            # NOTE: this deliberately mirrors `reported` (the clamped value, where
            # not-found-in-top-50 becomes MAX_REPORTED_POSITION), not the raw position.
            # A not-found listing is the least visible one, so it must land at the
            # aggressive end of the pricing ramp - writing raw NULL here would instead
            # make it look "unknown" and get neutral treatment.
            cur.executemany(
                "UPDATE active_listings SET search_position = %s WHERE user_id = %s AND item_id = %s",
                [(reported, user_id, item_id) for user_id, item_id, _, _, reported, _ in to_upsert],
            )


def recent_price_changes(now: datetime) -> dict[tuple[str, str], datetime]:
    """(user_id, item_id) -> when its price last changed, for changes still inside the
    reprice cooldown window. Feeds _suggestion_for_row; anything older is irrelevant to
    it, so the window is applied here rather than dragging the full history around.

    Runs on its own connection and swallows failures: price_change_log arrives in
    migration 0005, and a deployment that hasn't run it yet should lose the cooldown,
    not the whole research run. An empty map just means "nothing is cooling down"."""
    since = now - timedelta(days=REPRICE_COOLDOWN_DAYS)
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT user_id, item_id, max(changed_at) AS changed_at FROM price_change_log "
                "WHERE changed_at >= %s GROUP BY user_id, item_id",
                (since,),
            ).fetchall()
    except Exception as e:
        log.warning("Reprice cooldown lookup failed (has migration 0005 been run?): %s", e)
        return {}
    return {(str(r["user_id"]), str(r["item_id"])): r["changed_at"] for r in rows}


def _days_since_change(row, changes: dict[tuple[str, str], datetime], now: datetime) -> float | None:
    changed_at = changes.get((str(row["user_id"]), str(row["item_id"])))
    if changed_at is None:
        return None
    return (now - changed_at).total_seconds() / 86400


def _suggestion_for_row(row, active_snapshot: dict | None, days_since_price_change: float | None = None):
    """Run the suggested-price model for one active_listings row. Falls back to
    min_price when p25_price is absent, so rows still get a sane suggestion before a
    fresh research run has populated the newer column.

    A missing snapshot is passed through as empty anchors rather than short-circuited
    here, so the model still gets to apply the reprice cooldown - a listing repriced
    yesterday should report that, not an incidental 'no comps'."""
    matched_keyword = excluded_title_keyword(row.get("title"))
    if matched_keyword:
        return SuggestionResult(
            None, "excluded",
            {"v": 1, "status": "excluded", "matched_keyword": matched_keyword},
        )
    snapshot = active_snapshot or {}
    floor_anchor = snapshot.get("p25_price") or snapshot.get("min_price")
    return compute_suggested_price(
        current_price=float(row["price"]) if row["price"] is not None else None,
        anchor_avg=snapshot.get("avg_price"),
        anchor_floor=floor_anchor,
        comps=snapshot.get("sample_size"),
        days_listed=row.get("days_listed"),
        rank=row.get("search_position"),
        condition=row.get("condition"),
        shipping_charge=float(row["shipping_charge"]) if row.get("shipping_charge") is not None else None,
        # Mean shipping cost among today's comp pool - lets the model position on
        # total landed price (item + shipping) rather than item price alone. None
        # when no comp reported a cost (or migration 0007 hasn't been run), in which
        # case compute_suggested_price treats it as "no adjustment" rather than free.
        comp_avg_shipping=snapshot.get("avg_shipping"),
        watchers=row.get("watchers"),
        days_since_price_change=days_since_price_change,
    )


def update_active_listing_derived_columns(
    conn, card_query: str, active_snapshot: dict | None, today: date,
    price_changes: dict[tuple[str, str], datetime],
) -> int:
    """Apply this card's research to every user's matching active_listings rows in one pass
    (ports price_active_listings.py/avg_active_price.py::write_price_data).

    Also computes the stored suggested price. This runs immediately after
    research_card_positions() has written search_position in the same transaction, so
    every model input (price, condition, days_listed, rank) is current and consistent.

    price_changes comes from recent_price_changes() and is passed in rather than looked
    up here: `conn` is already a checked-out write connection, and taking a second one
    from a 5-slot pool while holding it invites a deadlock under concurrency."""
    rows = conn.execute(
        "SELECT user_id, item_id, price, condition, days_listed, search_position, shipping_charge, watchers, title "
        "FROM active_listings WHERE card = %s",
        (card_query,),
    ).fetchall()
    if not rows:
        return 0

    active_avg = active_snapshot["avg_price"] if active_snapshot else None
    last_checked = today if active_snapshot else None
    now = datetime.now(timezone.utc)

    updates = []
    for r in rows:
        price = r["price"]
        # Measured against the competitor average alone. It used to average that with
        # a TCGdex "sold" figure, which was a single market-price point, not sales.
        price_accuracy = None
        if price is not None and active_avg is not None and float(active_avg) != 0:
            price_accuracy = round((float(price) - float(active_avg)) / float(active_avg), 4)

        suggestion = _suggestion_for_row(r, active_snapshot, _days_since_change(r, price_changes, now))

        updates.append(
            (
                last_checked, active_avg, price_accuracy,
                suggestion.price, now, Json(suggestion.basis),
                r["user_id"], r["item_id"],
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE active_listings
               SET last_checked = COALESCE(%s, last_checked), active_avg_top5 = %s,
                   price_accuracy = %s,
                   suggested_price = %s, suggested_price_at = %s, suggested_price_basis = %s
               WHERE user_id = %s AND item_id = %s""",
            updates,
        )
    return len(updates)


def recompute_suggestions(user_id: str | None = None) -> dict:
    """Recompute stored suggestions from the most recent existing snapshots.

    Makes ZERO eBay calls - it reads whatever active_price_snapshots already holds. Used
    three ways: after a per-user sync (so new listings and daily days_listed drift get a
    suggestion without waiting for the 6h research cadence), as the backfill entry point
    after a model change, and for verification reruns."""
    where = "WHERE al.card IS NOT NULL AND al.card <> ''"
    params: list = []
    if user_id:
        where += " AND al.user_id = %s"
        params.append(user_id)

    # DISTINCT ON picks each card's newest snapshot row.
    sql = f"""
        SELECT al.user_id, al.item_id, al.price, al.condition, al.days_listed,
               al.search_position, al.shipping_charge, al.watchers, al.title,
               s.avg_price, s.min_price, s.p25_price, s.sample_size, s.avg_shipping
        FROM active_listings al
        LEFT JOIN LATERAL (
            SELECT avg_price, min_price, p25_price, sample_size, avg_shipping
            FROM active_price_snapshots aps
            WHERE aps.card_query = al.card
            ORDER BY aps.snapshot_date DESC LIMIT 1
        ) s ON true
        {where}
    """
    # Pre-migration-0007 fallback: same query minus avg_shipping, so a deployment
    # that hasn't run it yet degrades instead of failing every recompute.
    sql_no_shipping = f"""
        SELECT al.user_id, al.item_id, al.price, al.condition, al.days_listed,
               al.search_position, al.shipping_charge, al.watchers, al.title,
               s.avg_price, s.min_price, s.p25_price, s.sample_size
        FROM active_listings al
        LEFT JOIN LATERAL (
            SELECT avg_price, min_price, p25_price, sample_size
            FROM active_price_snapshots aps
            WHERE aps.card_query = al.card
            ORDER BY aps.snapshot_date DESC LIMIT 1
        ) s ON true
        {where}
    """
    now = datetime.now(timezone.utc)
    computed = nulled = clamped = cooldown = 0
    updates = []
    try:
        with get_db() as conn:
            rows = conn.execute(sql, params).fetchall()
    except psycopg.errors.UndefinedColumn:
        log.warning("active_price_snapshots.avg_shipping missing - has migration 0007 been run?")
        with get_db() as conn:
            rows = conn.execute(sql_no_shipping, params).fetchall()
    price_changes = recent_price_changes(now)

    for r in rows:
        snapshot = None
        if r["avg_price"] is not None:
            snapshot = _snapshot_from_row({
                "avg_price": r["avg_price"],
                "min_price": r["min_price"],
                "p25_price": r["p25_price"],
                "sample_size": r["sample_size"],
                "avg_shipping": r["avg_shipping"] if "avg_shipping" in r else None,
            })
        suggestion = _suggestion_for_row(r, snapshot, _days_since_change(r, price_changes, now))
        if suggestion.price is None:
            nulled += 1
            if suggestion.status == "cooldown":
                cooldown += 1
        else:
            computed += 1
            if suggestion.basis.get("clamps"):
                clamped += 1
        updates.append((suggestion.price, now, Json(suggestion.basis), r["user_id"], r["item_id"]))

    if updates:
        with get_db(read_only=False) as conn, conn.cursor() as cur:
            cur.executemany(
                """UPDATE active_listings
                   SET suggested_price = %s, suggested_price_at = %s, suggested_price_basis = %s
                   WHERE user_id = %s AND item_id = %s""",
                updates,
            )
    return {
        "rows": len(updates), "computed": computed, "null": nulled,
        "clamped": clamped, "cooldown": cooldown,
    }


def refresh_card(card_query: str) -> dict:
    """Force-refresh one card's comp research and every user's derived
    active_listings columns for it, synchronously. Backs the per-listing "Refresh" button
    on the listing detail page - deliberately bypasses run_shared_price_research's
    advisory lock/batch loop, since that machinery exists to serialize whole-catalog runs
    and would otherwise make a single-card refresh wait behind (or block) one."""
    today = datetime.now(timezone.utc).date()
    active_snapshot = research_card_active(card_query, today, force=True)

    with get_db() as conn:
        items = [
            dict(r)
            for r in conn.execute(
                "SELECT item_id, title, user_id FROM active_listings WHERE card = %s",
                (card_query,),
            ).fetchall()
        ]

    updated_rows = 0
    if items:
        price_changes = recent_price_changes(datetime.now(timezone.utc))
        with get_db(read_only=False) as conn:
            research_card_positions(conn, card_query, items, today)
            updated_rows = update_active_listing_derived_columns(
                conn, card_query, active_snapshot, today, price_changes
            )

    return {
        "status": "ok",
        "card_query": card_query,
        "active_found": active_snapshot is not None,
        "updated_rows": updated_rows,
    }


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

        found_active = errors = suggested_rows = 0
        timed_out = False
        # Read once for the whole run rather than per card: the window is 5 days wide,
        # so a change landing mid-run is already inside it and would only shift a
        # suggestion that is being suppressed either way.
        price_changes = recent_price_changes(started)
        # Same idea: our own item_ids are one set for the whole run. Reading them per
        # card meant ~200 full reads of active_listings against a remote database.
        # A listing added mid-run is simply not excluded from that run's pools, which
        # is what the previous per-card read achieved a few seconds earlier anyway.
        with get_db() as conn:
            own_ids = _own_item_ids(conn)

        tally = threading.Lock()

        def research_one(card: str) -> None:
            nonlocal found_active, errors, suggested_rows
            try:
                # force reaches the per-card functions, not just the researched-today
                # check above - otherwise a forced run silently reuses today's cached
                # snapshots and an algorithm change appears to have no effect. It is
                # aged, though: see _forced_recently.
                card_force = force and not _forced_recently(card)
                snapshot = research_card_active(card, today, force=card_force, own_ids=own_ids)

                # One checkout, not two: the read that used to take its own connection
                # runs on the write connection the next two calls need anyway.
                with get_db(read_only=False) as conn:
                    items = [
                        dict(r)
                        for r in conn.execute(
                            "SELECT item_id, title, user_id FROM active_listings WHERE card = %s",
                            (card,),
                        ).fetchall()
                    ]
                    rows = 0
                    if items:
                        research_card_positions(conn, card, items, today)
                        rows = update_active_listing_derived_columns(
                            conn, card, snapshot, today, price_changes
                        )
                if card_force:
                    _mark_researched(card)
                with tally:
                    if snapshot:
                        found_active += 1
                    suggested_rows += rows
            except Exception as e:
                with tally:
                    errors += 1
                log.error("Research failed for card '%s': %s", card, e)

        # Cards run RESEARCH_WORKERS at a time. The work is almost entirely waiting -
        # on eBay, then on a remote database - so overlapping it is most of the win;
        # _pace() keeps the rate eBay sees unchanged. Each worker holds at most one
        # pooled connection at a time, which is what keeps this under the pool size.
        with ThreadPoolExecutor(max_workers=RESEARCH_WORKERS) as pool:
            futures = {}
            for card in cards:
                futures[pool.submit(research_one, card)] = card
            for future in as_completed(futures):
                future.result()
                if (datetime.now(timezone.utc) - started).total_seconds() > MAX_RUN_SECONDS:
                    timed_out = True
                    # Only cards not yet started can be cancelled; whatever is already
                    # in flight finishes. They roll into the next run either way.
                    cancelled = sum(1 for f in futures if f.cancel())
                    if cancelled:
                        log.warning(
                            "Price research hit its %ds wall-clock budget - dropped %d/%d "
                            "cards, they'll be picked up on the next run",
                            MAX_RUN_SECONDS, cancelled, len(cards),
                        )
                    break
            # Any remaining futures are drained by the context manager on exit.

        summary = {
            "cards": len(cards),
            "active_found": found_active,
            "suggested_rows": suggested_rows,
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
