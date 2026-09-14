"""The seller's standing listing settings (`listing_defaults`, migration 0015).

Four required values the bulk-listing CSV needs and an inventory row cannot know:
where you ship from, and the exact Seller Hub names of your shipping, payment and
return policies. They are the same on every export forever, so they live on the
Settings page rather than being retyped per export.

A fifth, optional value sits alongside them: `min_price` (migration 0018), a seller-set
floor the Listing CSV's starting price is never allowed under. Unlike the four above it
never gates the CSV - `missing()` doesn't mention it, and None just means no minimum.

Beside them sits eBay's blank prefill template (migration 0017), stored once for the
same reason: it is one unchanging file that every prefill export needs, and eBay's
instructions forbid generating a replacement.

Read by two routers - `settings` shows and saves them, `inventory` fills the CSV and
the prefill template with them - so the query, the field list and the "is it configured
yet" rule live here rather than in both. Callers pass a connection in, the way
`inventory_value` does.
"""

from datetime import datetime, timezone

from psycopg.errors import UndefinedColumn

from dashboard.backend.services.listing_csv import DEFAULT_SHIPPING_PROFILE
from dashboard.backend.services.upsert_rules import existing_columns

MIGRATION_HINT = (
    "Listing defaults need db/migrations/0015_listing_defaults.sql to be run first"
)

MIN_PRICE_MIGRATION_HINT = (
    "A minimum listing price needs db/migrations/0018_listing_defaults_min_price.sql "
    "to be run first"
)

TEMPLATE_MIGRATION_HINT = (
    "Storing eBay's template needs db/migrations/0017_listing_defaults_prefill_template.sql "
    "to be run first"
)

# Every field is required before a CSV can be built. There is no partial-credit case:
# eBay rejects an upload missing any one of them, so a "some of them are set" state is
# not worth modelling.
FIELDS = ("item_location", "shipping_profile", "payment_profile", "return_profile")

# What a user who has never opened Settings starts from. Only the shipping profile
# gets a value, because it is the one field with a right answer independent of the
# seller: SHIPPING_PRICE_MAP in listing_economics.py has to recognise the name or the
# CSV's price floor assumes postage costs nothing. min_price is None, not 0 - None
# means "no seller-set minimum", the same as before this field existed.
BLANK = {f: "" for f in FIELDS} | {"shipping_profile": DEFAULT_SHIPPING_PROFILE, "min_price": None}


def _clean(value) -> str:
    return (value or "").strip()


def load(db, user_id) -> dict | None:
    """The user's settings, or None when migration 0015 hasn't been run.

    None rather than an exception so the Settings page can render the instructions,
    the same way `GET /inventory` reports `inventory_enabled: False` instead of
    failing. A user with no row yet gets BLANK, which is not an error either - it is
    just someone who hasn't set them up.

    `min_price` (0018) is read the same way the inventory row reads `manual_value` and
    `photo_urls` - via `existing_columns`, so an un-migrated database still returns the
    four required fields rather than failing the whole page.
    """
    present = existing_columns(db, "listing_defaults")
    if not present:
        return None
    has_min_price = "min_price" in present
    select_cols = list(FIELDS) + (["min_price"] if has_min_price else [])
    row = db.execute(
        f"SELECT {', '.join(select_cols)} FROM listing_defaults WHERE user_id = %s",
        [user_id],
    ).fetchone()
    if row is None:
        return dict(BLANK)
    # Stored nulls and stored blanks mean the same thing here, and the shipping
    # profile falls back to the default rather than to empty - an empty one would
    # silently price against $0 of postage.
    values = {f: _clean(row[f]) for f in FIELDS}
    return values | {
        "shipping_profile": values["shipping_profile"] or DEFAULT_SHIPPING_PROFILE,
        "min_price": float(row["min_price"]) if has_min_price and row["min_price"] is not None else None,
    }


def save(db, user_id, values: dict) -> dict:
    """Upsert the four required fields, plus min_price when the database has it.

    A min_price value is refused with MIN_PRICE_MIGRATION_HINT rather than silently
    dropped when 0018 hasn't been run - the same rule `_write` in routers/inventory.py
    follows for manual_value and photo_urls. A missing *table* (0015 outstanding)
    isn't checked here: the INSERT below still references the four required columns
    regardless, so psycopg raises its own UndefinedTable and the router already
    catches that.
    """
    present = existing_columns(db, "listing_defaults")
    has_min_price = "min_price" in present
    fields = list(FIELDS)
    params = {f: _clean(values.get(f)) or None for f in FIELDS}

    raw_min_price = values.get("min_price")
    if has_min_price:
        fields.append("min_price")
        params["min_price"] = round(float(raw_min_price), 2) if raw_min_price not in (None, "") else None
    elif present and raw_min_price not in (None, ""):
        # Table exists but lacks the column - a genuine "0018 not run" rather than
        # "0015 not run", which is why this checks `present` rather than firing
        # whenever has_min_price is false.
        raise UndefinedColumn(MIN_PRICE_MIGRATION_HINT)

    params["uid"] = user_id
    db.execute(
        f"""INSERT INTO listing_defaults (user_id, {', '.join(fields)})
            VALUES (%(uid)s, {', '.join(f'%({f})s' for f in fields)})
            ON CONFLICT (user_id) DO UPDATE SET
                {', '.join(f'{f} = EXCLUDED.{f}' for f in fields)}, updated_at = now()""",
        params,
    )
    result = {f: params[f] or "" for f in FIELDS}
    result["min_price"] = params.get("min_price")
    return result


def missing(values: dict) -> list[str]:
    """Which fields still have to be filled in before a CSV can be built."""
    return [f for f in FIELDS if not _clean(values.get(f))]


# --- eBay's blank prefill template (0017) ----------------------------------------
# Deliberately NOT in FIELDS. That SELECT runs on the listing-CSV path, which has no
# use for a workbook, and dragging tens of KB of bytea through a five-connection pool
# on every export would be paying for nothing.

def template_meta(db, user_id) -> dict | None:
    """Which template is on file and when it was stored - never the bytes.

    None means the column isn't there yet (0017 outstanding) or nothing is stored;
    both leave the Settings page asking for a file, which is the same instruction.
    """
    try:
        row = db.execute(
            "SELECT prefill_template_name, prefill_template_at, "
            # length() over the blob, so the page can show a size without the pool
            # carrying the file to do it.
            "length(prefill_template) AS size FROM listing_defaults WHERE user_id = %s",
            [user_id],
        ).fetchone()
    except UndefinedColumn:
        return None
    if row is None or row["size"] is None:
        return None
    return {
        "name": row["prefill_template_name"] or "template.xlsx",
        "uploaded_at": row["prefill_template_at"].isoformat() if row["prefill_template_at"] else None,
        "size": row["size"],
    }


def load_template(db, user_id) -> bytes | None:
    """The stored workbook, or None when there isn't one."""
    try:
        row = db.execute(
            "SELECT prefill_template FROM listing_defaults WHERE user_id = %s", [user_id],
        ).fetchone()
    except UndefinedColumn:
        return None
    return bytes(row["prefill_template"]) if row and row["prefill_template"] is not None else None


def save_template(db, user_id, name: str, data: bytes | None) -> None:
    """Store a template, or clear it by passing None.

    Its own upsert rather than a branch of `save`: the four text fields and the
    workbook are edited by different controls at different times, and one statement
    writing both would let saving a policy name wipe the file.
    """
    db.execute(
        """INSERT INTO listing_defaults
               (user_id, prefill_template, prefill_template_name, prefill_template_at)
           VALUES (%(uid)s, %(data)s, %(name)s, %(at)s)
           ON CONFLICT (user_id) DO UPDATE SET
               prefill_template = EXCLUDED.prefill_template,
               prefill_template_name = EXCLUDED.prefill_template_name,
               prefill_template_at = EXCLUDED.prefill_template_at,
               updated_at = now()""",
        {"uid": user_id, "data": data, "name": _clean(name) or None,
         "at": datetime.now(timezone.utc) if data is not None else None},
    )
