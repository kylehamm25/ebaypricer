"""Turn unlisted inventory rows into an eBay File Exchange CSV.

The last step of cataloguing a pile is listing it, and that is the one step this app
had nothing to say about: you looked at a row, retyped its name into eBay's listing
form, and hoped the title, grade and lot SKU came out the same way they do on every
other listing. This builds the bulk-upload file instead - one `Add` line per selected
row, filled from the same defaults the Chrome extension puts into the form by hand.

Three things are deliberately NOT in the output:

**No ad rate.** File Exchange can set a promoted-listing rate, and this does not.
Ad rates are real, not-trivially-reversible spend, which is why `auto_boost_promotion`
was taken out of the pipeline and `promotion_boost` only ever runs on a deliberate
request (see CLAUDE.md). A rate baked into a fifty-row bulk upload is exactly the
automatic ad spend that rule exists to prevent.

**No Best Offer.** Auto-accept and minimum-offer thresholds belong to the seller, the
same reason `revise_best_offer_thresholds` was deleted from `trading_api.py`. Creating
a listing must not decide them either.

**No graded cards.** Every price here descends from a comp pool that screens slabs out
(`comp_filter`), so this module has no number with which to price one. Condition is
always eBay's ungraded descriptor.

Pure: no DB, no network, no clock. Callers pass rows and their cached snapshots in,
the same way `inventory_value` works and for the same reason - the pricing here has to
be explainable from its inputs alone.
"""

import csv
import io

from dashboard.backend.services.suggested_price import (
    condition_multiplier,
    excluded_title_keyword,
    net_floor,
    psych_round,
)
from dashboard.backend.services.inventory_value import row_value
from ebaypricer.browse_api import CARD_CATEGORY_ID
from ebaypricer.cards import card_identity, find_catalog_card
from ebaypricer.listing_economics import shipping_charge_for_profile

# --- The seller's standard listing, as File Exchange spells it -------------------
# These MIRROR `ebay-defaults-extension/defaults.js`, which is the standard for what
# the extension types into eBay's own form. They are restated here rather than parsed
# out of that file because it is JavaScript, and its description is an array joined at
# runtime - a regex over it would break the first time someone reformats it.
#
# The consequence is a second copy: changing a default means changing both, and the
# `listing-defaults-audit` skill says so. What must NOT drift is the shipping profile
# name - `SHIPPING_PRICE_MAP` in listing_economics.py maps it to an assumed postage
# cost, and an unmapped name silently maps to $0, which would overstate the net on
# every price this module floors.
DEFAULT_SHIPPING_PROFILE = "Free ebay standard"

# Plain text in defaults.js because it goes into a textarea; eBay's description field
# is HTML, and a bare newline inside a CSV cell renders as nothing at all.
DESCRIPTION_HTML = (
    "<p><strong>Be sure to use code KLINKSUMMER for 10% off 3 or more cards!</strong></p>"
    # &amp;, not a bare ampersand: eBay's description field is HTML, and a raw '&'
    # is the one character in this text that would render wrongly.
    "<p><strong>Shipping &amp; Handling:</strong></p>"
    "<p>Combine orders for reduced shipping!</p>"
    "<ul>"
    "<li>Cards under $20 ship via eBay Standard Envelope with tracking</li>"
    "<li>$20+ cards ship in bubble mailers with USPS Ground Advantage</li>"
    "<li>Each card ships in a penny sleeve + top loader or card saver</li>"
    "<li>Orders are packaged securely to prevent bending or damage</li>"
    "</ul>"
    "<p>If you have any questions or need more photos, feel free to message me</p>"
    "<p>Thank you for supporting Klink TCG!</p>"
)

# defaults.js says "Buy It Now" and 0 lb 1 oz in 11x6x1 - the form's vocabulary.
# File Exchange wants its own.
FORMAT = "FixedPrice"
DEFAULT_DURATION = "GTC"
WEIGHT_MAJOR = 0
WEIGHT_MINOR = 1
PACKAGE_LENGTH = 11
PACKAGE_WIDTH = 6
PACKAGE_DEPTH = 1

# eBay's condition for a raw, unslabbed card in CARD_CATEGORY_ID. The actual grade
# rides in the CD:40001 condition descriptor below and in the title, not here - eBay
# has one id for every ungraded card.
CONDITION_ID_UNGRADED = "4000"

# eBay's own vocabulary for an ungraded card's condition, keyed by the grades this app
# uses (CONDITION_MULTIPLIER in suggested_price.py). Two different vocabularies for the
# same thing, so the mapping has to be written down somewhere; anything not in here is
# left blank and reported, rather than guessed at.
EBAY_CARD_CONDITION = {
    "near mint": "Near Mint or Better",
    "mint": "Near Mint or Better",
    "near mint or better": "Near Mint or Better",
    "lightly played": "Lightly Played (Excellent)",
    "moderately played": "Moderately Played (Very Good)",
    "heavily played": "Heavily Played (Poor)",
    "damaged": "Damaged",
}

# --- Card Condition, which is NOT an item specific -------------------------------
# eBay models an ungraded card's grade as a **condition descriptor**, a separate
# mechanism from aspects: descriptor 40001 ("Card Condition"), carried in its own
# `CD:40001` column, whose value is a numeric id rather than the words. Sending it as
# `C:Card Condition` - which is what this module did first - gets the whole row
# rejected with "Card Condition (40001) is a required field", because eBay never looks
# for the aspect at all.
#
# Ids are the CCG Individual Cards (183454) set. The base scale is 400010/11/12/13 and
# that category adds the played grades; the two overlap in meaning, so only one
# vocabulary is used here.
CD_CARD_CONDITION = "CD:40001"

CARD_CONDITION_DESCRIPTOR = {
    "near mint": "400010",              # Near mint or better
    "mint": "400010",
    "near mint or better": "400010",
    "lightly played": "400015",         # Lightly played (Excellent)
    "moderately played": "400016",      # Moderately played (Very good)
    "heavily played": "400017",         # Heavily played (Poor)
    # eBay has no "Damaged" descriptor - Poor is the bottom of its scale, and mapping
    # down to it is the honest direction. Mapping up to Heavily Played would describe
    # a damaged card as merely worn.
    "damaged": "400013",                # Poor
}

# What the grade is called in a title. `TITLE_CONDITION_MAP` in trading_api.py parses
# these back out, and `resolve_condition` prefers the title over eBay's own condition
# field - so the abbreviation here is what the card will be PRICED as once it is live.
# It therefore has to agree with the row's condition, which is why both come from the
# same field below and an unmapped grade emits no abbreviation at all rather than a
# plausible-looking one.
TITLE_GRADE = {
    "near mint": "NM",
    "mint": "NM",
    "near mint or better": "NM",
    "lightly played": "LP",
    "moderately played": "MP",
    "heavily played": "HP",
    "damaged": "DMG",
}

TITLE_MAX = 80

# The aspects this app fills, in the order both files carry them. Defined ahead of the
# column lists so each can build its own spelling from one source - File Exchange stars
# the required Game column ("*C:Game"), the draft template stars nothing - and so
# `card_aspects` below cannot drift from either.
# NB: no "Card Condition" - see CD_CARD_CONDITION above for why the grade is not an
# aspect. `card_aspects` still returns it, because eBay's prefill template asks for
# free-text aspects and the grade is worth stating there.
ASPECT_NAMES = (
    # Constant for every raw English single this app lists.
    "Game", "Language", "Graded", "Autographed", "Customized", "Vintage",
    "Card Size", "Material", "Age Level", "Country/Region of Manufacture", "Manufacturer",
    # Read off the catalog entry. Any of these is left BLANK rather than guessed when
    # the card can't be resolved - a wrong item specific is worse than a missing one,
    # because it is the wrong answer to a question buyers filter on.
    "Card Name", "Set", "Card Number", "Rarity", "Card Type", "Character",
    "Stage", "Speciality", "Features", "Finish",
)

# eBay's Card Type is the card's supertype, and the catalog already knows it - so a
# Trainer or Energy card is never described as a Pokemon, which is what assuming the
# constant would have done.
#
# Stage and Speciality both come out of `subtypes`, which mixes them into one list:
# ["Basic", "ex"] is a Basic-stage ex. Split by membership rather than position, since
# the order is not guaranteed.
STAGE_SUBTYPES = ("Basic", "Stage 1", "Stage 2", "VSTAR", "VMAX", "V-UNION", "Restored", "LEVEL-UP")
SPECIALITY_SUBTYPES = (
    "ex", "EX", "GX", "V", "VMAX", "VSTAR", "MEGA", "TAG TEAM", "BREAK", "Prime",
    "Tera", "Ultra Beast", "ACE SPEC", "Radiant", "Shining", "Star",
)

# eBay treats Pokemon as vintage through the Wizards of the Coast era, which ended when
# Nintendo took the licence back in 2003. Derived from the set's release date rather
# than from anything on the card, since that is the only thing that actually dates it.
VINTAGE_BEFORE_YEAR = 2004

# Written ahead of the header the way eBay's own downloaded templates are. File
# Exchange ignores lines starting with '#'.
INFO_LINE = "#INFO,Version=0.0.2,Template=fx_category_template_US"

# Order is not load-bearing for File Exchange - it reads by header name - but the
# starred columns are the required ones, and keeping them first makes a rejected
# upload readable when eBay names the column it did not like.
COLUMNS = [
    "*Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)",
    "CustomLabel",
    "*Category",
    "*Title",
    "*ConditionID",
    "*Description",
    "*Format",
    "*Duration",
    "*StartPrice",
    "*Quantity",
    "*Location",
    # Separate from *Location, which eBay treats as display text. Without this, a ZIP
    # in *Location alone comes back as "Please enter a valid postal code" (err:216007)
    # even when the ZIP is real - eBay wants the postcode in its own field.
    "PostalCode",
    "ShippingProfileName",
    "ReturnProfileName",
    "PaymentProfileName",
    "WeightMajor",
    "WeightMinor",
    "PackageLength",
    "PackageWidth",
    "PackageDepth",
    # Game is the one eBay requires, hence the star; the rest carry plain names.
    *(f"{'*' if name == 'Game' else ''}C:{name}" for name in ASPECT_NAMES),
    CD_CARD_CONDITION,
    # eBay refuses a listing with no photo (21919136), so this is required in
    # practice despite carrying no star. Pipe-separated, first one first.
    "PicURL",
]

# --- eBay's draft-listing template -----------------------------------------------
# A second, much shorter file, and the one to reach for when the drafts are going to
# be finished by hand: `Action=Draft` puts them in ebay.com/sh/lst/drafts instead of
# live on the site, and it takes **no business policies at all** - you pick those in
# the listing tool. That makes it the only export here with no Settings prerequisite.
#
# Its column names are eBay's, and they are NOT the File Exchange ones: "Custom label
# (SKU)" not "CustomLabel", "Category ID" not "*Category", "Price" not "*StartPrice",
# and no leading stars anywhere. Two spellings of the same idea, which is exactly why
# both sets are written out rather than derived from each other.
DRAFT_INFO_LINES = (
    "#INFO,Version=0.0.2,Template= eBay-draft-listings-template_US",
    "#INFO Action and Category ID are required fields. 1) Set Action to Draft",
    "#INFO After uploading from the Seller Hub Reports tab, complete your drafts at "
    "https://www.ebay.com/sh/lst/drafts",
)

DRAFT_COLUMNS = [
    "Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)",
    "Custom label (SKU)",
    "Category ID",
    "Title",
    "UPC",
    "Price",
    "Quantity",
    "Item photo URL",
    "Condition ID",
    "Description",
    "Format",
    # Item specifics, which eBay's starter file does NOT include. They are added here
    # because the draft template rides on the same File Exchange framework as the Add
    # one - the identical `Action(SiteID=...|Version=1193|CC=UTF-8)` preamble - and
    # that framework reads `C:<aspect>` columns by name. Unverified against a real
    # upload, so if eBay ever rejects the file for an unknown column, this block is
    # what to remove; nothing else here depends on it. Worth the try: aspects are how
    # a single gets found on eBay, and a draft that arrives with them is a draft you
    # do not have to fill in by hand.
    *(f"C:{name}" for name in ASPECT_NAMES),
    CD_CARD_CONDITION,
]


def identity(row: dict) -> dict:
    """Name, set and number for one row, however the row happens to know them.

    A row added from the catalog carries set_name and number outright. A free-text row
    carries neither - `card_query` is the words to search - so the same parser the comp
    filter uses is asked to pull an identity out of it. Blank rather than wrong when it
    can't: eBay rejects a bad item specific loudly, and invents nothing from a missing
    one.
    """
    name = (row.get("name") or "").strip()
    set_name = (row.get("set_name") or "").strip()
    number = (row.get("number") or "").strip()
    reverse = False

    ident = card_identity(row["card_query"]) if row.get("card_query") else None
    if ident:
        reverse = bool(ident.get("reverse"))
        set_name = set_name or (ident.get("set_name") or "").strip()
        number = number or (ident.get("number") or "").strip()
        name = name or (ident.get("name") or "").strip()

    out = {
        "name": name, "set_name": set_name, "number": number, "reverse": reverse,
        # Everything below is blank unless the catalog resolves the card. A free-text
        # row has a name and nothing else, and blank is the honest answer for it.
        "rarity": "", "supertype": "", "subtypes": [], "release": "",
    }

    card = find_catalog_card(row["card_query"]) if row.get("card_query") else None
    if card:
        out["rarity"] = (card.get("rarity") or "").strip()
        out["supertype"] = (card.get("supertype") or "").strip()
        out["subtypes"] = card.get("subtypes") or []
        out["release"] = (card.get("set_release") or "").strip()
    return out


def _first(values, allowed) -> str:
    """The first of `values` that `allowed` recognises, else blank."""
    return next((v for v in values if v in allowed), "")


def _character(ident: dict) -> str:
    """The Pokemon on the card, for the Character aspect.

    Only for Pokemon cards - a Trainer or Energy has no character, and naming one would
    be inventing a fact. The species is parsed by the same mapper the sprites used, so
    "N's Zoroark ex" and "Team Rocket's Articuno" resolve to the Pokemon rather than to
    the whole card name.
    """
    if ident["supertype"] != "Pokémon":
        return ""
    try:
        from dashboard.backend.utils.pokemon_sprites import get_sprite_mapper

        found = get_sprite_mapper().find_pokemon_in_title(ident["name"])
    except Exception:
        return ""
    # Title-cased because the mapper works in lowercase and eBay shows the value as-is.
    return found.title() if found else ""


def _vintage(release: str) -> str:
    """Yes / No / blank. Blank when the set's release date is unknown, since "No" would
    be a claim about a card whose age nothing here knows."""
    year = release[:4]
    if not year.isdigit():
        return ""
    return "Yes" if int(year) < VINTAGE_BEFORE_YEAR else "No"


def build_title(ident: dict, condition: str | None) -> str:
    """An 80-character title in this seller's usual shape.

    Trimmed from the least identifying end: "Pokemon TCG" goes before the set name,
    which goes before the card number, and the grade is appended last so it survives
    every trim. That order is not cosmetic - the grade is what `parse_condition_from_title`
    reads back, and a title that loses it gets priced off eBay's generic "Ungraded"
    instead.
    """
    grade = TITLE_GRADE.get((condition or "").strip().lower(), "")
    # Most identifying first, so a long name pushes out context rather than itself.
    # The number goes in bare, no '#'.
    parts = [ident["name"], ident["number"], ident["set_name"]]
    if ident["reverse"]:
        parts.append("Reverse Holo")
    optional = ["Pokemon TCG"]

    def assemble(head: list[str], tail: list[str]) -> str:
        out: list[str] = []
        for part in [*head, *tail, grade]:
            # A free-text row's name often already contains its own number and set
            # ("dragonite 12 mcdonalds"), and identity parses those back out of it -
            # so without this the title says each of them twice.
            if part and part.lower() not in " ".join(out).lower():
                out.append(part)
        return " ".join(out).strip()

    title = assemble(parts, optional)
    while len(title) > TITLE_MAX and optional:
        optional.pop()
        title = assemble(parts, optional)
    while len(title) > TITLE_MAX and len(parts) > 1:
        parts.pop()
        title = assemble(parts, optional)
    return title[:TITLE_MAX].strip()


def _effective_floor(shipping_charge: float, min_price: float | None) -> float:
    """The least a listing may open at: `net_floor` alone, or raised to the seller's
    own configured minimum (Settings, migration 0018) when one is set and higher.

    A shared helper rather than inlining `max(net_floor(...), min_price)` in both
    `listing_price` and `_draft`'s warning check, so the two can never disagree about
    which floor actually applied.
    """
    floor = net_floor(shipping_charge)
    return floor if min_price is None else max(floor, min_price)


def listing_price(unit_value: float, shipping_charge: float, min_price: float | None = None) -> float:
    """A starting ask for a card that has never been listed.

    NOT the suggested-price model. That model repositions a *live* listing - it needs
    the current price, how long it has sat, its search rank and its watchers, and an
    unlisted card has none of those, so pointing it at one would mean inventing four
    inputs. What is available is the number the Inventory page already shows: the
    condition-adjusted average of what competitors are asking today. Listing at it is a
    defensible opening position, and the seller edits it in the CSV or in Seller Hub.

    Two of the model's guardrails do carry over, because they are about the price
    itself rather than about a listing's history: `net_floor` keeps the ask above what
    still clears MIN_NET_PROCEEDS after fees and postage, and `psych_round` puts it on
    a real price ending. `min_price` is a third, optional floor the seller sets
    themselves on Settings - not part of the pricing model, just a standing "never
    below this" instruction applied at the same point net_floor is. Rounding runs after
    both floors and retries upward, the same ordering `compute_suggested_price` uses,
    so rounding can never re-cross either one.
    """
    floor = _effective_floor(shipping_charge, min_price)
    price = max(unit_value, floor)
    rounded = psych_round(price)
    if rounded < floor:
        rounded = psych_round(price, "up")
    return rounded


def _draft(
    row: dict, snap: dict | None, shipping_charge: float, min_price: float | None = None,
) -> tuple[dict | None, dict | None]:
    """One row as either a draft listing or a reason it can't be one."""
    def skip(reason: str):
        return None, {"id": row["id"], "name": row["name"], "reason": reason}

    if not row.get("card_query"):
        # Sealed product, bulk, or a row priced entirely by hand with no card behind
        # it. Those are not single cards, so CARD_CATEGORY_ID and its item specifics
        # would be wrong for them - and getting the category wrong is not a small
        # error, it is the listing appearing where nobody looking for it will search.
        return skip("No card behind this row — list sealed or bulk by hand")

    value = row_value(row, snap)
    if value["unit_value"] is None:
        # card_query is non-empty by here, so the only absence left is "nothing has
        # researched this card and no price was typed in".
        return skip("Not priced yet — price it first, or type a value in")

    ident = identity(row)
    if not ident["name"]:
        return skip("No name to build a title from")

    title = build_title(ident, row.get("condition"))
    price = listing_price(value["unit_value"], shipping_charge, min_price)
    photos = "|".join(u.strip() for u in (row.get("photo_urls") or "").split("|") if u.strip())

    warnings = []
    if not photos:
        # eBay rejects a photoless listing outright (21919136), so this is a failure
        # in waiting rather than a nicety. Warned rather than skipped: the row is
        # otherwise complete, and the fix is a photo URL on the row, not a smaller
        # selection.
        warnings.append("No photos — eBay will reject this row until it has at least one")
    keyword = excluded_title_keyword(title)
    if keyword:
        # The same list that makes `compute_suggested_price` decline. Worth saying at
        # listing time rather than discovering weeks later that one listing has never
        # once been repriced.
        warnings.append(
            f'Title contains "{keyword}" — this listing will never get an automatic '
            "price and needs pricing by hand",
        )
    if not value["condition_known"]:
        warnings.append(
            f'Condition "{row.get("condition") or "—"}" is not a recognised grade, so '
            "the price is unadjusted and the title carries no grade",
        )
    if not CARD_CONDITION_DESCRIPTOR.get((row.get("condition") or "").strip().lower()):
        # Card Condition is REQUIRED by eBay for this category, so a blank descriptor
        # is a guaranteed rejection rather than a missing nicety - said plainly, since
        # the fix is to set a grade on the row and nothing in the file can substitute.
        warnings.append("No eBay card condition for this grade — eBay will reject this row")
    if value["value_status"] == "manual":
        warnings.append("Priced from your stated value, not from comps")
    fee_floor = net_floor(shipping_charge)
    floor = _effective_floor(shipping_charge, min_price)
    if value["unit_value"] < floor:
        # Worth less than the floor it would take to sell it. The listing is still
        # legitimate - it just can't go out at what the card is worth, and saying so
        # beats the seller finding a $0.96 card priced at $2.99 and assuming the comps
        # are broken. Tested against the floor rather than against the final price, or
        # ordinary rounding up to a .99 ending would trip it constantly.
        if min_price is not None and floor == min_price and min_price > fee_floor:
            # The seller's own configured minimum did the raising here, not fees and
            # postage - worth saying which, since the two floors can disagree.
            warnings.append(
                f"Worth {value['unit_value']:.2f} — raised to {price:.2f}, your "
                "configured minimum price",
            )
        else:
            warnings.append(
                f"Worth {value['unit_value']:.2f} — raised to {price:.2f}, the least "
                "that still clears fees and postage",
            )
    if value["pool_filtered"] is False:
        warnings.append(
            "Priced from a comp pool taken before filtering existed — it may include "
            "graded slabs and multi-card lots, so the price may be high",
        )
    if not ident["set_name"] or not ident["number"]:
        warnings.append("No set or card number resolved — those item specifics are blank")

    return {
        "id": row["id"],
        "name": row["name"],
        "title": title,
        "price": price,
        "quantity": int(row.get("quantity") or 1),
        "sku": row.get("sku"),
        "condition": row.get("condition"),
        "card_condition": EBAY_CARD_CONDITION.get((row.get("condition") or "").strip().lower(), ""),
        "condition_descriptor": CARD_CONDITION_DESCRIPTOR.get(
            (row.get("condition") or "").strip().lower(), "",
        ),
        "value_status": value["value_status"],
        "unit_value": value["unit_value"],
        "photo_urls": photos,
        "ident": ident,
        "warnings": warnings,
    }, None


# The category as a human path rather than the leaf id. eBay's prefill template asks
# for "the category you list with in other marketplaces or your own store" and says it
# need not be mapped to eBay's taxonomy - but naming the one CARD_CATEGORY_ID actually
# points at gives its mapper the least room to land somewhere else.
CATEGORY_PATH = "Toys & Hobbies > Collectible Card Games > CCG Individual Cards"


def card_aspects(ident: dict, card_condition: str) -> dict[str, str]:
    """The item specifics for one card, keyed by eBay's aspect names.

    Shared by the File Exchange line below (as `C:` columns) and by the prefill
    template's pipe-separated Aspects cell. One copy, because the two files describing
    the same card differently is exactly the drift this app keeps removing.

    Blank values are kept rather than dropped: `_line` needs every key present to fill
    its fixed column set, and the prefill builder omits the empty ones itself.
    """
    subtypes = ident.get("subtypes") or []
    rarity = ident.get("rarity") or ""
    return {
        # --- true of every raw English single this app lists ---------------------
        "Game": "Pokémon TCG",
        "Language": "English",
        "Graded": "No",
        "Autographed": "No",
        "Customized": "No",
        "Vintage": _vintage(ident.get("release") or ""),
        "Card Size": "Standard",
        "Material": "Card Stock",
        "Age Level": "6+",
        "Country/Region of Manufacture": "United States",
        "Manufacturer": "The Pokémon Company",
        # --- read off the catalog -------------------------------------------------
        "Card Name": ident["name"],
        "Set": ident["set_name"],
        "Card Number": ident["number"],
        "Rarity": rarity,
        "Card Type": ident.get("supertype") or "",
        "Character": _character(ident),
        "Stage": _first(subtypes, STAGE_SUBTYPES),
        "Speciality": _first(subtypes, SPECIALITY_SUBTYPES),
        # Promo is a rarity in the catalog but reads as a feature on a listing, and a
        # reverse print is the other thing a buyer filters on. One value, not both:
        # File Exchange carries a single value per aspect column.
        "Features": "Reverse Holo" if ident["reverse"] else ("Promo" if "promo" in rarity.lower() else ""),
        # Only stated when the catalog says so outright. Most modern rares are holo
        # without saying it in the rarity, and guessing "Holo" on a card that isn't is
        # the kind of wrong specific a buyer opens a return over.
        "Finish": "Reverse Holo" if ident["reverse"] else ("Holo" if "holo" in rarity.lower() else ""),
        # Not an aspect - see CD_CARD_CONDITION. Kept in the dict because the prefill
        # template asks for free-text aspects, where the grade is worth stating.
        "Card Condition": card_condition,
    }


def _line(draft: dict, opts: dict) -> dict:
    aspects = card_aspects(draft["ident"], draft["card_condition"])
    return {
        "*Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)": "Add",
        # The lot SKU, which is not decoration: routers/lots.py groups every sold
        # order and active listing by exactly this string, so a listing created
        # without it never joins the lot it came out of.
        "CustomLabel": draft["sku"] or "",
        "*Category": CARD_CATEGORY_ID,
        "*Title": draft["title"],
        "*ConditionID": CONDITION_ID_UNGRADED,
        "*Description": DESCRIPTION_HTML,
        "*Format": FORMAT,
        "*Duration": opts["duration"],
        "*StartPrice": f"{draft['price']:.2f}",
        "*Quantity": draft["quantity"],
        "*Location": opts["item_location"],
        "PostalCode": opts["item_location"],
        "ShippingProfileName": opts["shipping_profile"],
        "ReturnProfileName": opts["return_profile"],
        "PaymentProfileName": opts["payment_profile"],
        "WeightMajor": WEIGHT_MAJOR,
        "WeightMinor": WEIGHT_MINOR,
        "PackageLength": PACKAGE_LENGTH,
        "PackageWidth": PACKAGE_WIDTH,
        "PackageDepth": PACKAGE_DEPTH,
        # Starred because eBay requires Game; the rest carry the same names. Driven by
        # ASPECT_NAMES rather than by the dict, since card_aspects also returns the
        # grade, which is a descriptor here and not an aspect.
        "*C:Game": aspects["Game"],
        **{f"C:{name}": aspects[name] for name in ASPECT_NAMES if name != "Game"},
        CD_CARD_CONDITION: draft["condition_descriptor"],
        "PicURL": draft["photo_urls"],
    }


def _draft_line(draft: dict) -> dict:
    """One row in eBay's draft-listing template. No policies, no location, no weight -
    that file has no columns for them, and the listing tool asks at step two."""
    return {
        "Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)": "Draft",
        "Custom label (SKU)": draft["sku"] or "",
        "Category ID": CARD_CATEGORY_ID,
        "Title": draft["title"],
        # Pokemon singles have no barcode. Left blank rather than omitted, so the row
        # still lines up with the header eBay's own sample uses.
        "UPC": "",
        "Price": f"{draft['price']:.2f}",
        "Quantity": draft["quantity"],
        "Item photo URL": draft["photo_urls"],
        "Condition ID": CONDITION_ID_UNGRADED,
        "Description": DESCRIPTION_HTML,
        "Format": FORMAT,
        # The same aspects the Add file carries, in the draft template's unstarred
        # spelling. See DRAFT_COLUMNS for why they are here at all.
        **{f"C:{name}": value
           for name, value in card_aspects(draft["ident"], draft["card_condition"]).items()
           if name in ASPECT_NAMES},
        CD_CARD_CONDITION: draft["condition_descriptor"],
    }


# The two files this module can write. "draft" lands rows in ebay.com/sh/lst/drafts
# for finishing by hand; "add" creates the listings outright.
MODES = ("draft", "add")

# BOTH files are delimited text, and neither may be a workbook. Tried once as .xlsx and
# eBay refused it outright: "We had trouble reading your file. Make sure to stick to
# commas, semicolons, or tabs to separate your data." Only the PREFILL template is a
# workbook - that is a different tool (services/prefill_template.py), and the two are
# easy to conflate because eBay hands them both out from the Reports tab.


def build(rows: list[dict], snapshots: dict[str, dict], opts: dict, mode: str = "add") -> dict:
    """Drafts, skips and the CSV itself.

    Returns everything the caller needs to show what is about to be uploaded before it
    is downloaded - a row that can't be listed says why, in its own line, instead of
    quietly not appearing in the file.

    `mode` picks which of eBay's two templates to write. The rows are decided
    identically either way - same title, same price, same floor - so the choice is
    only about which columns carry them, and whether the result is a draft or a
    listing.
    """
    shipping_charge = shipping_charge_for_profile(opts["shipping_profile"])
    min_price = opts.get("min_price")

    drafts, skipped = [], []
    for row in rows:
        draft, skip = _draft(row, snapshots.get(row.get("card_query")), shipping_charge, min_price)
        (skipped if draft is None else drafts).append(skip or draft)

    draft_mode = mode == "draft"
    columns = DRAFT_COLUMNS if draft_mode else COLUMNS
    info = DRAFT_INFO_LINES if draft_mode else (INFO_LINE,)
    lines = [_draft_line(d) if draft_mode else _line(d, opts) for d in drafts]

    # The ident dict was only ever scaffolding for the title and the item specifics.
    for draft in drafts:
        draft.pop("ident", None)

    return {
        "csv": _to_csv(info, columns, lines) if drafts else "",
        "drafts": drafts,
        "skipped": skipped,
        # Postage assumed behind the floor, so the dialog can say which profile it
        # priced against rather than leaving the number unexplained.
        "shipping_charge": shipping_charge,
        "mode": mode,
    }


def _to_csv(info, columns: list[str], lines: list[dict]) -> str:
    buf = io.StringIO()
    # CRLF, which is what eBay's templates use and what the csv module writes by
    # default; set out loud because the default is easy to change by accident.
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\r\n")
    for line in info:
        buf.write(line + "\r\n")
    writer.writeheader()
    for line in lines:
        writer.writerow(line)
    return buf.getvalue()
