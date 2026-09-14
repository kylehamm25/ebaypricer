"""Per-user settings the app itself owns.

Distinct from `routers/ebay.py`, which is about the OAuth connection - that is a
relationship with eBay, this is a handful of values the user typed. Currently just the
listing defaults behind the bulk-listing CSV (`listing_defaults`, migration 0015).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from psycopg.errors import UndefinedColumn, UndefinedTable
from pydantic import BaseModel, Field

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services import inventory_value, listing_settings
from dashboard.backend.services import prefill_template as prefill_template_service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class ListingDefaults(BaseModel):
    """All four required fields, always - this is a form that saves as a unit.

    Blank is allowed on save: half-filled settings are a normal state on the way to
    filled ones, and it is the CSV endpoint, not this one, that insists on all four.
    Refusing a partial save would mean losing the two fields you had looked up while
    you go and find the third.

    min_price is the odd one out: optional, never gates the CSV, and null means "no
    seller-set minimum" rather than "not filled in yet". See listing_csv.listing_price.
    """
    item_location: str = Field("", max_length=60)
    shipping_profile: str = Field("", max_length=80)
    payment_profile: str = Field("", max_length=80)
    return_profile: str = Field("", max_length=80)
    min_price: float | None = Field(None, ge=0, le=100_000)


def _payload(values: dict | None, template: dict | None = None) -> dict:
    if values is None:
        # Migration 0015 outstanding. Reported rather than raised so the page renders
        # the instructions, the same way GET /inventory handles a missing 0011.
        return {"listing_defaults": dict(listing_settings.BLANK),
                "listing_defaults_enabled": False, "missing": list(listing_settings.FIELDS),
                "prefill_template": None}
    return {"listing_defaults": values, "listing_defaults_enabled": True,
            "missing": listing_settings.missing(values),
            # Name, date and size only - never the workbook itself. Null means none is
            # stored, which is also what an un-migrated 0017 looks like: both leave the
            # page asking for a file, which is the same instruction either way.
            "prefill_template": template}


@router.get("/listing-defaults")
def get_listing_defaults(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        # One connection for both - the pool is 5, and neither read is worth a second.
        return _payload(
            listing_settings.load(db, user_id), listing_settings.template_meta(db, user_id),
        )


@router.put("/listing-defaults")
def put_listing_defaults(
    body: ListingDefaults, user_id: UUID = Depends(get_current_user_id),
):
    """Save the form, and - when a minimum price is set - raise every inventory row
    already worth less than it up to that floor.

    A minimum wouldn't mean much if it only applied to cards catalogued from here on;
    the point is that nothing in the pile sits under it, so saving one is also the
    trigger that goes and enforces it on what is already there. See
    `inventory_value.raise_below_minimum` for what that does and does not touch.
    """
    try:
        with get_db(read_only=False) as db:
            values = listing_settings.save(db, user_id, body.model_dump())
            raised = (
                inventory_value.raise_below_minimum(db, user_id, values["min_price"])
                if values["min_price"] is not None else 0
            )
    except UndefinedTable:
        raise HTTPException(503, listing_settings.MIGRATION_HINT)
    except UndefinedColumn:
        raise HTTPException(503, listing_settings.MIN_PRICE_MIGRATION_HINT)
    # Re-read rather than echoing back: the template is written by a different
    # endpoint, and a response that omitted it would blank it in the page's cache.
    with get_db() as db:
        return {**_payload(values, listing_settings.template_meta(db, user_id)),
                "raised_to_minimum": raised}


# openpyxl reads .xlsx only, and eBay's template is one. Refused by name rather than by
# letting load_workbook raise something unreadable.
TEMPLATE_SUFFIX = ".xlsx"

# Far past any real template - eBay's is tens of KB - and small enough that a stray
# upload cannot put something enormous in a bytea column.
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024


@router.put("/prefill-template")
async def put_prefill_template(
    file: UploadFile = File(...), user_id: UUID = Depends(get_current_user_id),
):
    """Store eBay's blank prefill template, so exports stop asking for it.

    The file is checked here rather than at export time: a template rejected on this
    page costs one re-download, while one rejected mid-export wastes the selection that
    was about to be written into it. What comes back says which sheet and columns were
    found, so a template eBay has since revised is visible now.
    """
    if not (file.filename or "").lower().endswith(TEMPLATE_SUFFIX):
        raise HTTPException(422, f"Upload eBay's template as {TEMPLATE_SUFFIX} — got {file.filename!r}")
    data = await file.read()
    if len(data) > MAX_TEMPLATE_BYTES:
        raise HTTPException(422, f"That file is larger than {MAX_TEMPLATE_BYTES // (1024 * 1024)}MB")

    try:
        found = prefill_template_service.validate(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    try:
        with get_db(read_only=False) as db:
            listing_settings.save_template(db, user_id, file.filename or "", data)
    except UndefinedColumn:
        raise HTTPException(503, listing_settings.TEMPLATE_MIGRATION_HINT)
    except UndefinedTable:
        raise HTTPException(503, listing_settings.MIGRATION_HINT)

    with get_db() as db:
        return {**found, **_payload(listing_settings.load(db, user_id),
                                    listing_settings.template_meta(db, user_id))}


@router.delete("/prefill-template")
def delete_prefill_template(user_id: UUID = Depends(get_current_user_id)):
    try:
        with get_db(read_only=False) as db:
            listing_settings.save_template(db, user_id, "", None)
    except UndefinedColumn:
        raise HTTPException(503, listing_settings.TEMPLATE_MIGRATION_HINT)
    except UndefinedTable:
        raise HTTPException(503, listing_settings.MIGRATION_HINT)
    with get_db() as db:
        return _payload(listing_settings.load(db, user_id), listing_settings.template_meta(db, user_id))
