"""Unlisted inventory: cards owned but not yet listed on eBay.

Every other table in this app is a projection of something eBay already knows.
This one is not - eBay has no idea what is sitting in a box on the desk, so these
rows are hand-entered and nothing ever syncs, overwrites or reconciles them
(table `inventory`, migration 0011).

Value is read from the SHARED comp snapshots and never researched here. That is a
hard rule, not an optimisation: a pile can hold hundreds of distinct cards, and
the ebay-api-rate-limits skill forbids researching in a request handler - one page
load would otherwise fire hundreds of Browse calls and starve the scheduled run
that keeps real listings priced. So a row shows a value when some earlier run
happened to have researched that card, and shows nothing when it didn't. The
response says which, rather than dressing an absent number up as zero.
"""

import base64
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from psycopg.errors import UndefinedColumn, UndefinedTable
from pydantic import BaseModel, Field

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services import listing_csv, listing_settings, photo_storage
from dashboard.backend.services import prefill_template as prefill_template_service
from dashboard.backend.services.inventory_value import latest_snapshots, row_value
from dashboard.backend.services.type_sort import sort_by_card_type
from dashboard.backend.services.upsert_rules import existing_columns
from ebaypricer.browse_api import web_search_url
from ebaypricer.cards import image_url_for_query

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

MIGRATION_HINT = "Unlisted inventory needs db/migrations/0011_inventory.sql to be run first"

# Sorting is done in SQL so it stays correct across the whole pile rather than
# within whatever the page happens to hold - there is no pagination here (the whole
# pile comes back in one response), so "the whole pile" and "the page" are the same
# thing, but the SQL path is still cheaper when a real column exists. Value is NOT
# sortable this way: it is computed after the query from a snapshot that may not
# exist, so ordering by it in SQL isn't possible at all. Type (below) is the same
# kind of computed field - the catalog lives in a local file, not a joinable table -
# but unlike Value it's only ever grouped into a handful of buckets, so a plain Python
# sort of the already-fetched, unpaginated rows is exact rather than an
# approximation, at the cost of a catalog lookup per distinct card - see SORT_TYPE_KEY
# below.
_SORT_COLS = {
    "name": "name",
    "number": "number",
    "quantity": "quantity",
    "location": "location",
    "sku": "sku",
    "condition": "condition",
    "cost": "cost",
    "added": "created_at",
}

# Not in _SORT_COLS - "type" has no column, so it can't be an ORDER BY key. Handled
# entirely in Python after the fetch (see the sort applied near the end of
# list_inventory), keyed off this constant so the SQL fallback and the post-fetch
# check can never name it differently.
SORT_TYPE_KEY = "type"

_BASE_COLUMNS = (
    "id", "name", "card_query", "set_name", "number", "condition", "quantity",
    "location", "sku", "cost", "notes", "created_at", "updated_at",
)

# Columns added by migrations later than 0011, which may not have been run.
# Selected only when present; _row treats a missing key exactly like a null one.
_OPTIONAL_COLUMNS = ("manual_value", "archived_at", "photo_urls")


def _select_for(db) -> tuple[str, set[str]]:
    """The widest SELECT this database can actually answer, and what it includes.

    One information_schema query rather than a tuple of hand-written fallback
    SELECTs: with two optional columns that tuple would already need four entries,
    and the next migration would double it again.
    """
    present = existing_columns(db, "inventory")
    optional = {c for c in _OPTIONAL_COLUMNS if c in present}
    return ", ".join([*_BASE_COLUMNS, *sorted(optional)]), optional


class InventoryItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    card_query: str | None = Field(None, max_length=200)
    set_name: str | None = Field(None, max_length=120)
    number: str | None = Field(None, max_length=32)
    condition: str | None = Field(None, max_length=40)
    quantity: int = Field(1, ge=1, le=100000)
    location: str | None = Field(None, max_length=120)
    sku: str | None = Field(None, max_length=40)
    cost: float | None = Field(None, ge=0)
    # Per unit, like cost. Set means "this is what it is worth, don't ask the
    # market" - see _value for why the condition multiplier does not touch it.
    manual_value: float | None = Field(None, ge=0)
    # Up to MAX_PHOTOS web-hosted links, pipe-separated, first one first - eBay's own
    # format for the prefill template's photo cell, stored the way it is used.
    photo_urls: str | None = Field(None, max_length=4000)
    notes: str | None = None


def _clean(value: str | None) -> str | None:
    """Blank and whitespace-only mean "not recorded", which is null - otherwise the
    location filter grows an empty-string bucket that looks like a real shelf."""
    v = (value or "").strip()
    return v or None


def _f(value) -> float | None:
    return float(value) if value is not None else None


# eBay's ceiling on photos per item, and its requirement that every link be https.
# Enforced on save rather than on export: a link rejected now costs one correction,
# whereas one rejected after a prefill upload costs the whole round trip.
MAX_PHOTOS = 24


def _clean_photos(value: str | None) -> str | None:
    """Normalise the pipe-separated photo list, or refuse it.

    Order is meaningful - eBay reads the FIRST link to work out what the item is - so
    this only ever trims and drops blanks, never sorts or dedupes.
    """
    links = [u.strip() for u in (value or "").split("|")]
    links = [u for u in links if u]
    if not links:
        return None
    if len(links) > MAX_PHOTOS:
        raise HTTPException(422, f"eBay allows at most {MAX_PHOTOS} photos per item")
    bad = [u for u in links if not u.lower().startswith("https://")]
    if bad:
        raise HTTPException(422, f"Photo links must start with https:// — {bad[0]}")
    return "|".join(links)


def _card_images(card_queries: list[str]) -> dict[str, str | None]:
    """Art URL per distinct card. Resolved from card_query because that string
    carries the set NAME while the art CDN is keyed on set ID - the same reason
    routers/active.py resolves it rather than storing it.

    Distinct, not per row: each call re-reads the 37KB card_query lookup off disk
    (~0.2ms), which is nothing for one card and pointless to repeat for twenty
    copies of it. No network is involved either way.
    """
    return {q: image_url_for_query(q) for q in set(card_queries)}


def _sort_by_type(items: list[dict], direction: str) -> list[dict]:
    """Applies SORT_TYPE_KEY in Python, since there is no column to ORDER BY in SQL -
    see the note above _SORT_COLS. Thin wrapper over the shared helper, which
    documents the ordering rule; this only adapts it to the inventory row shape."""
    return sort_by_card_type(
        items,
        direction=direction,
        query_of=lambda i: i["card_query"],
        number_of=lambda i: i.get("number"),
        id_of=lambda i: i["id"],
    )


def _row(row: dict, snap: dict | None, image_url: str | None) -> dict:
    item = {
        "id": row["id"],
        "name": row["name"],
        "card_query": row["card_query"],
        "set_name": row["set_name"],
        "number": row["number"],
        "condition": row["condition"],
        "quantity": int(row["quantity"] or 1),
        "location": row["location"],
        "sku": row["sku"],
        "cost": _f(row["cost"]),
        # .get, not [...]: absent entirely when migration 0012 hasn't been run.
        "manual_value": _f(row.get("manual_value")),
        # Absent entirely before migration 0016, which reads the same as no photos.
        "photo_urls": row.get("photo_urls"),
        "notes": row["notes"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        # When this row left the pile. Null means it is still in it. NOT a claim
        # that the card is listed on eBay - see migration 0014.
        "archived_at": row["archived_at"].isoformat() if row.get("archived_at") else None,
        # Real card art when the row is a catalog card. Null for anything the
        # catalog can't resolve - sealed, bulk, free-text rows - which the page
        # draws as a card back, the same as the Active and Sold pages do. The
        # species sprite this used to fall back to could not tell two printings
        # apart (every Charizard shares one) and read as a picture of the card.
        "card_image_url": image_url,
        # The same eBay search the comps came from, as a link a person can open -
        # built in browse_api beside the query constants so it can't drift from
        # what was actually asked for. Pure string work, no network. None when the
        # row has no card_query, which is the one case there is no search behind.
        "search_url": web_search_url(row["card_query"]) if row["card_query"] else None,
    }
    item.update(row_value(row, snap))
    # Per-unit cost times quantity, so the totals below can just sum a column.
    item["total_cost"] = round(item["cost"] * item["quantity"], 2) if item["cost"] is not None else None
    return item


def _totals(items: list[dict]) -> dict:
    valued = [i for i in items if i["total_value"] is not None]
    costed = [i for i in items if i["total_cost"] is not None]
    return {
        "entries": len(items),
        "units": sum(i["quantity"] for i in items),
        "value": round(sum(i["total_value"] for i in valued), 2),
        # How much of the pile that value actually covers. Without this the number
        # reads as "the whole pile is worth this", which it is not.
        "valued_entries": len(valued),
        "cost": round(sum(i["total_cost"] for i in costed), 2),
        "costed_entries": len(costed),
    }


@router.get("")
def list_inventory(
    user_id: UUID = Depends(get_current_user_id),
    location: str = Query(None),
    sku: str = Query(None),
    q: str = Query(None),
    # active (still in the pile) | archived (dealt with) | all. Not a bool, because
    # "show me both" is a real thing to want and a bool cannot say it.
    archived: str = Query("active"),
    sort_by: str = Query(SORT_TYPE_KEY),
    sort_dir: str = Query("asc"),
):
    where = ["user_id = %(uid)s"]
    params: dict = {"uid": user_id}
    if location:
        where.append("COALESCE(location, '') = %(location)s")
        params["location"] = location
    if sku:
        where.append("COALESCE(sku, '') = %(sku)s")
        params["sku"] = sku
    if q:
        # ILIKE for the same reason routers/sold.py uses it: Postgres LIKE is
        # case-sensitive, and nobody types a card name with the right capitals.
        where.append("(name ILIKE %(q)s OR COALESCE(notes, '') ILIKE %(q)s)")
        params["q"] = f"%{q}%"

    sort_col = _SORT_COLS.get(sort_by, "created_at")
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    # NULLS LAST on every sort: a blank location or cost is the least interesting
    # row whichever direction was asked for. id DESC breaks ties so paging and
    # re-sorts are stable.
    order_sql = f"ORDER BY {sort_col} {dir_sql} NULLS LAST, id DESC"

    with get_db() as db:
        try:
            columns, optional = _select_for(db)
            # Archived rows have left the pile, so they drop out of every ordinary
            # read - the totals and the filter menus below included.
            if "archived_at" in optional:
                if archived == "archived":
                    where.append("archived_at IS NOT NULL")
                elif archived != "all":
                    where.append("archived_at IS NULL")
            elif archived == "archived":
                # Migration 0014 not run, so nothing can be archived. An empty list
                # is the truth; without this the archive view would show the whole
                # pile, which reads as "you have archived everything".
                where.append("FALSE")
            rows = [dict(r) for r in db.execute(
                f"SELECT {columns} FROM inventory WHERE {' AND '.join(where)} {order_sql}",
                params,
            ).fetchall()]
            # Filter options come from the whole pile, not the filtered result -
            # otherwise picking a location empties the menu you picked it from.
            locations = [r["location"] for r in db.execute(
                "SELECT DISTINCT location FROM inventory "
                "WHERE user_id = %s AND location IS NOT NULL ORDER BY location",
                [user_id],
            ).fetchall()]
            skus = [r["sku"] for r in db.execute(
                "SELECT DISTINCT sku FROM inventory "
                "WHERE user_id = %s AND sku IS NOT NULL ORDER BY sku",
                [user_id],
            ).fetchall()]
            queries = [r["card_query"] for r in rows if r["card_query"]]
            snaps = latest_snapshots(db, queries)
        except UndefinedTable:
            # Migration 0011 not run. Reported rather than raised so the page can
            # render the instructions instead of a failure.
            return {"items": [], "totals": _totals([]), "locations": [], "skus": [],
                    "inventory_enabled": False}

    # Outside the connection block: the catalog is a local file, and holding a
    # pooled connection across it would be for nothing (the pool is 5).
    images = _card_images(queries)
    items = [_row(r, snaps.get(r["card_query"]), images.get(r["card_query"])) for r in rows]
    if sort_by == SORT_TYPE_KEY:
        items = _sort_by_type(items, sort_dir)
    return {
        "items": items,
        "totals": _totals(items),
        "locations": locations,
        "skus": skus,
        "inventory_enabled": True,
        # Whether the app can host photos at all. Reported so the edit dialog offers
        # the uploader or explains its absence, rather than presenting a button that
        # fails per file on a project with no Supabase credentials.
        "photo_hosting_enabled": photo_storage.configured(),
    }


# Same pair-of-statements shape as _SELECTS and for the same reason: the first
# writes manual_value, the second is the pre-0012 fallback. A supplied manual value
# is refused rather than silently dropped by the fallback - see _write.
# Columns every install has (0011). Order is only for readability - the statements
# below are built from these names, so nothing has to be kept in step by hand.
_WRITE_COLUMNS = (
    "name", "card_query", "set_name", "number", "condition", "quantity",
    "location", "sku", "cost", "notes",
)

# Columns a later migration added, written only when the database has them. Each one
# names the migration to run, because a value supplied for a missing column is refused
# out loud rather than silently dropped - a stated price that vanished would show the
# row as unpriced with no explanation, and photos that vanished would come back as an
# empty prefill cell.
_OPTIONAL_WRITE_COLUMNS = {
    "manual_value":
        "A stated price needs db/migrations/0012_inventory_manual_value.sql to be run first",
    "photo_urls":
        "Photos need db/migrations/0016_inventory_photo_urls.sql to be run first",
}


def _write(params: dict, item_id: int | None = None):
    """Insert or update a row, using the widest column set this database can take.

    Built from `existing_columns` rather than from a tuple of hand-written fallback
    statements, for the reason `_select_for` gives about reads: two optional columns
    already need four statements and the next migration doubles it again. One
    information_schema query per write is a fair price for that not happening.
    """
    with get_db(read_only=False) as db:
        present = existing_columns(db, "inventory")
        if not present:
            raise HTTPException(503, MIGRATION_HINT)

        columns = list(_WRITE_COLUMNS)
        for column, hint in _OPTIONAL_WRITE_COLUMNS.items():
            if column in present:
                columns.append(column)
            elif params.get(column) is not None:
                raise HTTPException(503, hint)

        if item_id is None:
            sql = (
                f"INSERT INTO inventory (user_id, {', '.join(columns)}) "
                f"VALUES (%(uid)s, {', '.join(f'%({c})s' for c in columns)}) "
                "RETURNING id"
            )
        else:
            params["id"] = item_id
            sql = (
                f"UPDATE inventory SET {', '.join(f'{c} = %({c})s' for c in columns)}, "
                "updated_at = now() WHERE id = %(id)s AND user_id = %(uid)s RETURNING id"
            )
        return db.execute(sql, params).fetchone()


def _params(body: InventoryItem, user_id: UUID) -> dict:
    return {
        "uid": user_id,
        "name": body.name.strip(),
        "card_query": _clean(body.card_query),
        "set_name": _clean(body.set_name),
        "number": _clean(body.number),
        "condition": _clean(body.condition),
        "quantity": body.quantity,
        "location": _clean(body.location),
        "sku": _clean(body.sku),
        "cost": body.cost,
        "manual_value": body.manual_value,
        "photo_urls": _clean_photos(body.photo_urls),
        "notes": _clean(body.notes),
    }


@router.post("", status_code=201)
def create_item(body: InventoryItem, user_id: UUID = Depends(get_current_user_id)):
    params = _params(body, user_id)
    if not params["name"]:
        raise HTTPException(422, "A name is required")
    row = _write(params)
    return {"status": "ok", "id": row["id"]}


@router.put("/{item_id}")
def update_item(item_id: int, body: InventoryItem, user_id: UUID = Depends(get_current_user_id)):
    params = _params(body, user_id)
    if not params["name"]:
        raise HTTPException(422, "A name is required")
    row = _write(params, item_id)
    # user_id in the WHERE means a miss is either "gone" or "not yours", and those
    # answer identically on purpose - distinguishing them would confirm that
    # somebody else's row exists.
    if row is None:
        raise HTTPException(404, "No such inventory item")
    return {"status": "ok", "id": item_id}


@router.post("/{item_id}/duplicate", status_code=201)
def duplicate_item(item_id: int, user_id: UUID = Depends(get_current_user_id)):
    """Copy a row's fields into a brand new one - the quick way to catalogue a second
    physical copy of the same card, or to split a stack across two locations without
    retyping name, condition, cost and everything else by hand.

    A plain insert of what `_select_for` can read, run back through `_write` so it
    degrades on a pre-0012/0016 database exactly like a normal create does. Not
    archived (a copy belongs in the pile even if the original has since left it),
    and photos come along - they are a picture of the card, still true of a second
    one of it.
    """
    with get_db() as db:
        try:
            columns, _ = _select_for(db)
            row = db.execute(
                f"SELECT {columns} FROM inventory WHERE id = %s AND user_id = %s",
                [item_id, user_id],
            ).fetchone()
        except UndefinedTable:
            raise HTTPException(503, MIGRATION_HINT)
    if row is None:
        raise HTTPException(404, "No such inventory item")

    params = {
        "uid": user_id,
        "name": row["name"],
        "card_query": row["card_query"],
        "set_name": row["set_name"],
        "number": row["number"],
        "condition": row["condition"],
        "quantity": row["quantity"],
        "location": row["location"],
        "sku": row["sku"],
        "cost": row["cost"],
        "manual_value": row.get("manual_value"),
        "photo_urls": row.get("photo_urls"),
        "notes": row["notes"],
    }
    new_row = _write(params)
    return {"status": "ok", "id": new_row["id"]}


class BulkIds(BaseModel):
    # Capped because this is one statement over a list the client chose. 500 is far
    # past any plausible hand-selection and keeps the parameter array sane.
    ids: list[int] = Field(..., min_length=1, max_length=500)


class BulkUpdate(BulkIds):
    """Only the fields actually sent are written.

    That distinction is the whole point: `model_fields_set` separates "leave this
    alone" (key absent) from "clear it" (key present and null), which a plain
    default of None cannot express. Deliberately limited to the three fields that
    describe a whole stack of cards at once - where they live, which lot they came
    from, what grade they are. Prices are per-card judgements and are not in here.
    """
    location: str | None = None
    sku: str | None = None
    condition: str | None = None


_BULK_COLUMNS = {"location": "location", "sku": "sku", "condition": "condition"}


@router.post("/bulk-update")
def bulk_update(body: BulkUpdate, user_id: UUID = Depends(get_current_user_id)):
    changed = [f for f in body.model_fields_set if f in _BULK_COLUMNS]
    if not changed:
        raise HTTPException(422, "Nothing to change")
    # Column names come from _BULK_COLUMNS, never from the request - the field names
    # are only ever used to look them up.
    sets = ", ".join(f"{_BULK_COLUMNS[f]} = %({f})s" for f in changed)
    params = {f: _clean(getattr(body, f)) for f in changed}
    params.update(uid=user_id, ids=body.ids)
    try:
        with get_db(read_only=False) as db:
            rows = db.execute(
                f"UPDATE inventory SET {sets}, updated_at = now() "
                "WHERE user_id = %(uid)s AND id = ANY(%(ids)s) RETURNING id",
                params,
            ).fetchall()
    except UndefinedTable:
        raise HTTPException(503, MIGRATION_HINT)
    # Scoped by user_id, so ids that aren't yours simply don't come back - the count
    # is what actually changed, not what was asked for.
    return {"status": "ok", "updated": len(rows), "fields": changed}


class ListingCsvRequest(BulkIds):
    """Which of eBay's two templates to build.

    "draft" lands the rows in ebay.com/sh/lst/drafts to be finished in the listing
    tool; "add" creates the listings outright. Only "add" needs the Settings values -
    the draft template has no business-policy columns at all, which is why the check
    below is skipped for it rather than being a blanket precondition.
    """
    mode: str = "draft"


@router.post("/listing-csv")
def listing_csv_for_items(
    body: ListingCsvRequest, user_id: UUID = Depends(get_current_user_id),
):
    """An eBay File Exchange CSV for the selected rows, with a report of what is in it.

    Two files, chosen by `mode`. "draft" writes eBay's draft-listing template, whose
    rows land in ebay.com/sh/lst/drafts to be finished in the listing tool; "add"
    writes the File Exchange template, whose rows become listings outright. Both carry
    the same title, price and photos, so the choice is about how much is settled here
    versus in Seller Hub.

    Everything the "add" file needs beyond the rows themselves -
    where you ship from, and the exact Seller Hub names of your shipping, payment and
    return policies - is the same on every export forever, so it lives on the Settings
    page (`listing_defaults`, migration 0015) instead of being retyped each time. An
    unconfigured user gets a 400 naming the missing fields rather than a file eBay
    would reject: a wrong policy name is the commonest cause of a rejected upload, and
    a guessed one is worse than no file.

    Returns the file as a string beside the per-row drafts rather than as a download,
    so the page can show what is about to be uploaded first. That matters more here
    than the extra step costs: every line becomes a live listing at a price this app
    chose, and the `ebay-listing-dry-run` skill's preview-then-confirm rule is the
    house style for anything that ends in a marketplace write - even one a human still
    has to upload.

    Reads only, and never researches: prices come from whatever `active_price_snapshots`
    already holds, exactly as `GET /inventory` does. A row nothing has priced is
    reported as skipped, not quietly listed at a guess.
    """
    if body.mode not in listing_csv.MODES:
        raise HTTPException(422, f"mode must be one of {', '.join(listing_csv.MODES)}")

    with get_db() as db:
        # Both reads share the one connection - the pool is 5, and taking a second
        # while holding this one is what database.py warns against.
        defaults = listing_settings.load(db, user_id)
        if defaults is None:
            raise HTTPException(503, listing_settings.MIGRATION_HINT)
        # Only the "add" file carries policies and a location. Demanding them for a
        # draft would block the one export that needs nothing set up - and the draft
        # route exists precisely because those names are the fiddly part.
        gaps = listing_settings.missing(defaults) if body.mode == "add" else []
        if gaps:
            raise HTTPException(
                400,
                "Set your listing defaults on the Settings page first — missing "
                + ", ".join(g.replace("_", " ") for g in gaps),
            )
        try:
            columns, _ = _select_for(db)
            rows = [dict(r) for r in db.execute(
                # Scoped by user_id in the WHERE, like the other bulk endpoints: ids
                # that aren't yours simply don't come back.
                f"SELECT {columns} FROM inventory "
                "WHERE user_id = %s AND id = ANY(%s) ORDER BY name, id",
                [user_id, body.ids],
            ).fetchall()]
            snaps = latest_snapshots(db, [r["card_query"] for r in rows if r["card_query"]])
        except UndefinedTable:
            raise HTTPException(503, MIGRATION_HINT)

    if not rows:
        raise HTTPException(404, "None of those inventory items exist")

    # Outside the connection block: building titles reads the local card catalog off
    # disk, and the pool is 5.
    result = listing_csv.build(
        rows, snaps, defaults | {"duration": listing_csv.DEFAULT_DURATION}, body.mode,
    )
    kind = "drafts" if body.mode == "draft" else "listings"
    result["filename"] = f"ebay-{kind}-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return result


# eBay's own ceiling: "up to 1,000 listings in a single upload". Higher than BulkIds'
# 500 because this is not a hand-made selection - cataloguing a box and prefilling the
# whole thing is the normal way to use it.
MAX_PREFILL_ROWS = 1000


@router.post("/prefill-template")
def prefill_template(body: BulkIds, user_id: UUID = Depends(get_current_user_id)):
    """Fill eBay's prefill listing template with the selected rows.

    Step 1 of eBay's three-step round trip: this hands back your stored template with a
    row per card written into it, you upload that to Seller Hub, eBay returns a file of
    suggested categories, titles and aspects, and you finish that file there. Steps 2
    and 3 are not in this app.

    Takes ids and nothing else. The workbook is eBay's own - their instructions say not
    to change the file's formatting, so it is edited in place rather than generated -
    and it is kept on the Settings page, since it is one unchanging file every export
    needs. Everything it doesn't recognise is handed back untouched; see
    `services/prefill_template.py`.

    Reads only, and never researches: the prefill file carries no price at all, so
    unlike the File Exchange CSV an unpriced row is perfectly listable here.
    """
    if len(body.ids) > MAX_PREFILL_ROWS:
        raise HTTPException(
            422,
            f"eBay takes at most {MAX_PREFILL_ROWS} listings in one upload; that is {len(body.ids)}",
        )

    with get_db() as db:
        # Template and rows on one connection - the pool is 5.
        template = listing_settings.load_template(db, user_id)
        # Only for naming the download, so the file that comes back is recognisably a
        # copy of the one on file rather than something new.
        meta = listing_settings.template_meta(db, user_id)
        if template is None:
            raise HTTPException(
                400, "Upload eBay's blank prefill template on the Settings page first",
            )
        try:
            columns, _ = _select_for(db)
            rows = [dict(r) for r in db.execute(
                # Scoped by user_id, like every other bulk endpoint here.
                f"SELECT {columns} FROM inventory "
                "WHERE user_id = %s AND id = ANY(%s) ORDER BY name, id",
                [user_id, body.ids],
            ).fetchall()]
        except UndefinedTable:
            raise HTTPException(503, MIGRATION_HINT)

    if not rows:
        raise HTTPException(404, "None of those inventory items exist")

    try:
        result = prefill_template_service.fill(template, rows)
    except ValueError as exc:
        # The stored file is no longer readable as the template - eBay revised it, or
        # the wrong file got saved. The message names what was looked for, and the fix
        # is a new upload on Settings.
        raise HTTPException(422, f"{exc} Replace it on the Settings page.")

    # Base64 rather than a file response: the report of what went in and what was left
    # out has to reach the page too, and one round trip carrying both beats a download
    # that silently drops rows. The template is tens of KB, so the 33% is nothing.
    return {
        "filename": (meta or {}).get("name") or "ebay-prefill.xlsx",
        "workbook": base64.b64encode(result.pop("file")).decode("ascii"),
        **result,
    }


def _photos_of(db, item_id: int, user_id: UUID) -> list[str]:
    """The row's photo list, and proof the row is yours.

    Raises 404 for a row that is missing OR someone else's - the same answer to both,
    on purpose, since distinguishing them would confirm another user's row exists.
    """
    try:
        row = db.execute(
            "SELECT photo_urls FROM inventory WHERE id = %s AND user_id = %s",
            [item_id, user_id],
        ).fetchone()
    except UndefinedColumn:
        raise HTTPException(503, _OPTIONAL_WRITE_COLUMNS["photo_urls"])
    except UndefinedTable:
        raise HTTPException(503, MIGRATION_HINT)
    if row is None:
        raise HTTPException(404, "No such inventory item")
    return [u.strip() for u in (row["photo_urls"] or "").split("|") if u.strip()]


def _save_photos(db, item_id: int, user_id: UUID, urls: list[str]) -> None:
    db.execute(
        "UPDATE inventory SET photo_urls = %s, updated_at = now() "
        "WHERE id = %s AND user_id = %s",
        ["|".join(urls) or None, item_id, user_id],
    )


@router.post("/{item_id}/photos")
async def add_photos(
    item_id: int,
    files: list[UploadFile] = File(...),
    user_id: UUID = Depends(get_current_user_id),
):
    """Host photos of this card and append them to the row.

    eBay will only take a photo as a public https URL ending in an image extension -
    it fetches them itself, anonymously - so an upload here is what turns a card on the
    desk into something every export can carry. See `services/photo_storage.py` for
    why the bucket is Supabase's rather than eBay Picture Services'.

    Appends rather than replaces, and preserves order: eBay reads the FIRST photo to
    identify the item, so the order these arrive in is the order they are listed in.
    """
    if not photo_storage.configured():
        raise HTTPException(503, "Photo hosting needs SUPABASE_URL and SUPABASE_SERVICE_KEY")

    with get_db() as db:
        existing = _photos_of(db, item_id, user_id)

    room = MAX_PHOTOS - len(existing)
    if room <= 0:
        raise HTTPException(422, f"This row already has eBay's limit of {MAX_PHOTOS} photos")
    if len(files) > room:
        raise HTTPException(422, f"Only {room} more photo{'s' if room > 1 else ''} will fit")

    # Uploaded outside any DB transaction: each file is a network round trip to
    # Supabase, and the pool is 5.
    added = []
    for f in files:
        try:
            added.append(photo_storage.upload(user_id, item_id, await f.read(), f.content_type or ""))
        except photo_storage.PhotoStorageError as exc:
            # Whatever already landed is kept and recorded below rather than orphaned
            # in the bucket - a partial upload the user can see beats a silent leak.
            if added:
                with get_db(read_only=False) as db:
                    _save_photos(db, item_id, user_id, existing + added)
            raise HTTPException(422, f"{f.filename}: {exc}")

    with get_db(read_only=False) as db:
        _save_photos(db, item_id, user_id, existing + added)
    return {"status": "ok", "id": item_id, "photo_urls": existing + added, "added": len(added)}


class PhotoRef(BaseModel):
    url: str = Field(..., min_length=1, max_length=1000)


class PhotoOrder(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=64)


@router.post("/{item_id}/photos/reorder")
def reorder_photos(item_id: int, body: PhotoOrder, user_id: UUID = Depends(get_current_user_id)):
    """Put the row's photos in a given order. Which one is first is the whole point:
    eBay uses the first photo as the listing's main image, and its prefill flow reads
    that one to work out what the item is.

    The submitted list must be a permutation of what the row already holds - the same
    URLs, reordered. Anything else is rejected rather than reconciled, because a
    reorder that could also add or drop photos is a second, riskier endpoint wearing
    this one's name.
    """
    with get_db() as db:
        existing = _photos_of(db, item_id, user_id)
    if sorted(body.urls) != sorted(existing):
        raise HTTPException(422, "That isn't the same set of photos this row has")

    with get_db(read_only=False) as db:
        _save_photos(db, item_id, user_id, body.urls)
    return {"status": "ok", "id": item_id, "photo_urls": body.urls}


@router.post("/{item_id}/photos/remove")
def remove_photo(item_id: int, body: PhotoRef, user_id: UUID = Depends(get_current_user_id)):
    """Drop one photo from the row, and from the bucket if we host it.

    The row is updated first. If the bucket delete then fails the file is orphaned,
    which costs a few hundred KB - far better than the reverse, where the row keeps a
    URL that no longer resolves and every future export carries a dead link.
    """
    with get_db() as db:
        existing = _photos_of(db, item_id, user_id)
    if body.url not in existing:
        raise HTTPException(404, "That photo isn't on this row")

    remaining = [u for u in existing if u != body.url]
    with get_db(read_only=False) as db:
        _save_photos(db, item_id, user_id, remaining)
    photo_storage.delete(body.url)
    return {"status": "ok", "id": item_id, "photo_urls": remaining}


ARCHIVE_MIGRATION_HINT = (
    "Archiving needs db/migrations/0014_inventory_archived.sql to be run first"
)


class BulkArchive(BulkIds):
    """archived=True files the rows away; False puts them back in the pile."""
    archived: bool = True


def _set_archived(user_id: UUID, ids: list[int], archived: bool) -> int:
    try:
        with get_db(read_only=False) as db:
            rows = db.execute(
                # A timestamp, not a flag: when you were done with it is worth
                # keeping, and it costs nothing over a boolean.
                "UPDATE inventory SET archived_at = %s, updated_at = now() "
                "WHERE user_id = %s AND id = ANY(%s) RETURNING id",
                [datetime.now(timezone.utc) if archived else None, user_id, ids],
            ).fetchall()
    except UndefinedColumn:
        raise HTTPException(503, ARCHIVE_MIGRATION_HINT)
    except UndefinedTable:
        raise HTTPException(503, MIGRATION_HINT)
    return len(rows)


@router.post("/bulk-archive")
def bulk_archive(body: BulkArchive, user_id: UUID = Depends(get_current_user_id)):
    n = _set_archived(user_id, body.ids, body.archived)
    return {"status": "ok", "archived" if body.archived else "restored": n}


@router.post("/{item_id}/archive")
def archive_item(item_id: int, user_id: UUID = Depends(get_current_user_id)):
    """Take one row out of the pile - what you press once you have listed the card.

    Deliberately not a delete: deleting throws away the condition, location, lot and
    researched price, so an ended listing or a mis-click leaves nothing to restore.
    """
    if not _set_archived(user_id, [item_id], True):
        raise HTTPException(404, "No such inventory item")
    return {"status": "ok", "id": item_id}


@router.post("/{item_id}/unarchive")
def unarchive_item(item_id: int, user_id: UUID = Depends(get_current_user_id)):
    if not _set_archived(user_id, [item_id], False):
        raise HTTPException(404, "No such inventory item")
    return {"status": "ok", "id": item_id}


@router.post("/bulk-delete")
def bulk_delete(body: BulkIds, user_id: UUID = Depends(get_current_user_id)):
    try:
        with get_db(read_only=False) as db:
            rows = db.execute(
                "DELETE FROM inventory WHERE user_id = %s AND id = ANY(%s) RETURNING id",
                [user_id, body.ids],
            ).fetchall()
    except UndefinedTable:
        raise HTTPException(503, MIGRATION_HINT)
    return {"status": "ok", "deleted": len(rows)}


@router.delete("/{item_id}")
def delete_item(item_id: int, user_id: UUID = Depends(get_current_user_id)):
    try:
        with get_db(read_only=False) as db:
            row = db.execute(
                "DELETE FROM inventory WHERE id = %s AND user_id = %s RETURNING id",
                [item_id, user_id],
            ).fetchone()
    except UndefinedTable:
        raise HTTPException(503, MIGRATION_HINT)
    if row is None:
        raise HTTPException(404, "No such inventory item")
    return {"status": "ok", "id": item_id}
