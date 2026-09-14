"""Fill in eBay's prefill listing template from unlisted inventory rows.

A different route to a listing from the File Exchange CSV next door, and a three-step
round trip rather than one file:

  1. You put eBay's blank template on the Settings page once, and this fills a copy of
     it - SKU, photos, title, category, aspects - one row per selected card.
  2. You upload it; eBay reads it and hands back a file of suggested categories, titles
     and item aspects.
  3. You review that file, complete it and upload it again to create the listings.

Only step 1 lives here. Steps 2 and 3 happen in Seller Hub.

**The workbook is edited, never regenerated.** eBay's instructions say in as many words
not to change the formatting, and the template is a styled multi-sheet workbook with a
GETTING STARTED tab beside the data one. So this opens the stored file,
writes cells into the existing sheet and hands the same workbook back: every style,
every other tab, every column this code does not recognise survives because nothing
ever rewrites them.

**Columns are found by header text, not by position.** Nothing here hardcodes "column
C". eBay revises these templates, and a fixed letter that silently shifts one column
would write titles into the category cell - visibly wrong only after the upload. A
header this cannot find is reported instead, and the export refuses rather than
guessing.

The listing details - title, category and aspects - come from `listing_csv`, so the two
files describe the same card the same way.
"""

import io
import re

from openpyxl import load_workbook

from dashboard.backend.services.listing_csv import (
    CATEGORY_PATH,
    EBAY_CARD_CONDITION,
    build_title,
    card_aspects,
    identity,
)

# The data sheet, per eBay's instructions. Matched loosely (case and punctuation
# folded) because the name has to survive being read off a screenshot of the tab.
SHEET_NAME = "eBay-prefill-listing-template"

# eBay's own ceiling. Mirrored from routers/inventory.py, which enforces it on save -
# restated here because a row stored before that check existed could still hold more.
MAX_PHOTOS = 24

# The header this code writes, and the labels it will accept for it. Only Title is
# required: eBay's Set A is satisfied by title alone, and everything else is optional
# by its own documentation, so a template missing them still produces a usable file.
#
# Keys are internal names; the tuples are lowercase substrings matched against the
# header cell, longest-first so "item photo url" cannot be claimed by a looser rule.
_HEADERS = {
    "custom_label": ("custom label", "sku"),
    "photo_urls": ("item photo url", "photo url", "picture url"),
    "title": ("item title", "title"),
    "category": ("category",),
    "aspects": ("aspects", "item specifics"),
}

REQUIRED_HEADERS = ("title",)

# How far down to look for the header row. eBay's templates put instructions above the
# table; ten rows is well past that and stops a huge sheet being scanned in full.
_HEADER_SEARCH_ROWS = 10


def _norm(value) -> str:
    """Header text with case, punctuation and runs of whitespace folded away, so
    "Item Photo URL", "item photo url " and "Item  Photo-URL" all match."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def find_sheet(wb):
    """The data sheet, by name, then by having a recognisable header row.

    The fallback matters: this file is downloaded, opened in Excel and saved again by
    people, and a renamed tab should not be the thing that stops the export.
    """
    target = _norm(SHEET_NAME)
    for ws in wb.worksheets:
        if _norm(ws.title) == target:
            return ws
    for ws in wb.worksheets:
        if find_headers(ws)[0]:
            return ws
    return None


def find_headers(ws) -> tuple[dict, int | None]:
    """Which column each known header sits in, and which row they are on.

    Returns the first row that carries a Title column, since that is the one header
    every usable template has. Column numbers are 1-based, as openpyxl counts them.
    """
    for row in ws.iter_rows(min_row=1, max_row=_HEADER_SEARCH_ROWS):
        found = {}
        for cell in row:
            text = _norm(cell.value)
            if not text:
                continue
            padded = f" {text} "
            for key, labels in _HEADERS.items():
                if key in found:
                    continue
                # Whole-word, not substring: "Subtitle" normalises to one word
                # containing "title", and a loose match would put every card's title
                # in the subtitle column. Longest label first so "item photo url"
                # wins over a looser rule if one is ever added.
                if any(f" {label} " in padded for label in sorted(labels, key=len, reverse=True)):
                    found[key] = cell.column
                    break
        if "title" in found:
            return found, row[0].row
    return {}, None


def first_empty_row(ws, header_row: int, columns: dict) -> int:
    """The first row under the header with nothing in any known column.

    Appended to rather than overwritten: a seller part-way through a template should
    not lose the rows they typed by hand, and `ws.max_row` alone would skip past
    trailing blank-but-styled rows that eBay's templates carry.
    """
    last_used = header_row
    for r in range(header_row + 1, ws.max_row + 1):
        if any(ws.cell(row=r, column=c).value not in (None, "") for c in columns.values()):
            last_used = r
    return last_used + 1


def _photos(row: dict) -> tuple[str, str | None]:
    """The photo cell for one row, and a warning if it needed trimming.

    Order is preserved exactly - eBay reads the first link to work out what the item
    is - so an over-long list is cut from the end rather than sampled.
    """
    links = [u.strip() for u in (row.get("photo_urls") or "").split("|") if u.strip()]
    if not links:
        return "", None
    if len(links) > MAX_PHOTOS:
        return "|".join(links[:MAX_PHOTOS]), (
            f"Has {len(links)} photos — only the first {MAX_PHOTOS} were written, which "
            "is all eBay accepts"
        )
    return "|".join(links), None


def _aspects_cell(ident: dict, condition: str | None) -> str:
    """Aspects as eBay wants them in one cell: `Name=Value` pairs joined by pipes.

    Empty values are dropped here rather than in `card_aspects`, which keeps them for
    the File Exchange columns. `Features=` with nothing after it reads as an assertion
    that the card has no features, which is not the same as not saying.
    """
    pairs = card_aspects(ident, EBAY_CARD_CONDITION.get((condition or "").strip().lower(), ""))
    return "|".join(f"{name}={value}" for name, value in pairs.items() if value)


def _draft(row: dict) -> tuple[dict | None, dict | None]:
    """One row as either a prefill line or a reason it can't be one."""
    if not row.get("card_query"):
        # Sealed product, bulk, or a hand-priced row with no card behind it. The
        # category and aspects below are a single card's, so those rows would be
        # described wrongly rather than incompletely.
        return None, {"id": row["id"], "name": row["name"],
                      "reason": "No card behind this row — prefill sealed or bulk by hand"}

    ident = identity(row)
    if not ident["name"]:
        return None, {"id": row["id"], "name": row["name"],
                      "reason": "No name to build a title from"}

    photos, photo_warning = _photos(row)
    warnings = [photo_warning] if photo_warning else []
    if not photos:
        # Not fatal: Set A is satisfied by Title alone and Set B by Category and
        # Aspects, both of which are filled. Worth saying, because eBay reads the
        # first photo to identify the item and its suggestions are better with one.
        warnings.append("No photos — eBay's suggestions are better with at least one")
    if not ident["set_name"] or not ident["number"]:
        warnings.append("No set or card number resolved — those aspects are left out")

    return {
        "id": row["id"],
        "name": row["name"],
        # The lot SKU, deliberately not a unique per-row key. eBay only "recommends"
        # this column for correlating results, whereas routers/lots.py groups every
        # order and listing by exactly this string - so a listing that ends up with
        # anything else in its Custom Label never joins the lot it came out of. Rows
        # are correlated by their title instead, which is unique per card anyway.
        "custom_label": row.get("sku") or "",
        "photo_urls": photos,
        "title": build_title(ident, row.get("condition")),
        "category": CATEGORY_PATH,
        "aspects": _aspects_cell(ident, row.get("condition")),
        "warnings": warnings,
    }, None


def _open(workbook_bytes: bytes):
    """The workbook, its data sheet, its known columns and its header row.

    Raises ValueError with a message naming what it looked for, for anything that
    isn't eBay's template. Shared by `validate` and `fill` so a file accepted on the
    Settings page cannot then be rejected at export time.
    """
    # keep_vba is not set: the templates are .xlsx, and asking openpyxl to preserve
    # macros on a file that has none rewrites it for nothing.
    try:
        wb = load_workbook(io.BytesIO(workbook_bytes))
    except Exception as exc:
        # Anything openpyxl refuses to open - a renamed .xls, a truncated download, a
        # file that was never a workbook. Caught broadly on purpose: it raises several
        # unrelated types (BadZipFile, InvalidFileException, KeyError on a mangled
        # archive), and to the caller they all mean the same thing.
        raise ValueError(f"Couldn't read that file as an Excel workbook ({exc})") from exc

    ws = find_sheet(wb)
    if ws is None:
        raise ValueError(
            f"No '{SHEET_NAME}' sheet in that file, and no other sheet has a Title "
            "column — is it eBay's prefill template?",
        )

    columns, header_row = find_headers(ws)
    gaps = [h for h in REQUIRED_HEADERS if h not in columns]
    if gaps:
        raise ValueError(
            "Couldn't find the " + ", ".join(gaps) + " column on that sheet — is it "
            "eBay's prefill template?",
        )
    return wb, ws, columns, header_row


def validate(workbook_bytes: bytes) -> dict:
    """What a candidate template is, without writing anything to it.

    Run when the file is stored rather than when it is used: a template rejected on
    the Settings page costs one re-download, while one rejected mid-export wastes the
    selection that was about to be written into it.
    """
    _wb, ws, columns, _header_row = _open(workbook_bytes)
    return {
        "sheet": ws.title,
        # Which of the five this template actually has. One without a photo or aspects
        # column is still usable, and saying so up front beats the seller noticing the
        # data is missing after the round trip.
        "columns": sorted(columns),
        "missing_columns": sorted(set(_HEADERS) - set(columns)),
    }


def fill(workbook_bytes: bytes, rows: list[dict]) -> dict:
    """Write the rows into the stored template and hand the workbook back.

    Returns the filled file alongside a report of what went into it and what didn't,
    so the page can show both before anything is downloaded.
    """
    wb, ws, columns, header_row = _open(workbook_bytes)

    drafts, skipped = [], []
    for row in rows:
        draft, skip = _draft(row)
        (skipped if draft is None else drafts).append(skip or draft)

    start = first_empty_row(ws, header_row, columns)
    for offset, draft in enumerate(drafts):
        for key, column in columns.items():
            ws.cell(row=start + offset, column=column, value=draft[key])

    out = io.BytesIO()
    wb.save(out)
    return {
        "file": out.getvalue(),
        "drafts": drafts,
        "skipped": skipped,
        "sheet": ws.title,
        "first_row": start,
        "columns": sorted(columns),
        "missing_columns": sorted(set(_HEADERS) - set(columns)),
    }
