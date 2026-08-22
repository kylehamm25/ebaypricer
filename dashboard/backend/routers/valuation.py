"""Ad-hoc card valuation: look a card up by name and see what it's worth right now.

Answers a different question from the rest of the app. Everything else prices cards we
already own; this prices cards we're thinking about BUYING - typically a pile someone
is offering as a lot - so it has to work for any of the ~20,000 cards in the catalog,
not just the ~215 we have listed.

That difference drives the whole design. Only about 1.4% of the catalog has a cached
price snapshot, so nearly every lookup needs a live eBay call:

  /cards/search  - free. Pure local scan of the cached card DB (cards.search_cards),
                   no network at all, safe to call on every keystroke.
  /card          - costs one Browse call per card per day. Reuses today's snapshot when
                   there is one, and is capped (see MAX_BATCH) because this is the first
                   feature where a USER, not a scheduled job, decides how many eBay
                   calls happen. See the ebay-api-rate-limits skill.

Deliberately stateless: nothing is persisted per user. A valuation is a question, not a
record. Saved lists and "convert to lot" come later.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services.price_research import research_card_active
from dashboard.backend.services.suggested_price import condition_multiplier
# The module-level helper, which falls back to the Pikachu sprite when it finds no
# Pokemon in the string. That is what routers/active.py and routers/sold.py already do,
# so a Trainer card looks the same here as it does on every other page. The trade is
# that Pikachu means "nothing matched" as often as it means "this is a Pikachu" - the
# mapper's own get_sprite_url() returns None instead, if that distinction is ever wanted.
from dashboard.backend.utils.pokemon_sprites import get_sprite_url
from ebaypricer.cards import _fmt_card, _lookup_price, card_identity, card_image_url
# cards.get_db() is the card CATALOG; database.get_db() is the Postgres pool. Two very
# different things with the same name - aliased so neither can be reached for by mistake.
from ebaypricer.cards import get_db as get_card_catalog
from ebaypricer.browse_api import web_search_url
from ebaypricer.listing_economics import estimate_fees_and_net

router = APIRouter(prefix="/api/v1/valuation", tags=["valuation"])

# Hard ceiling on cards valued in one request. Each uncached card is one Browse call, so
# without this a single paste could fire hundreds of them and starve the scheduled
# research run that keeps real listings priced.
MAX_BATCH = 25

SEARCH_LIMIT_MAX = 50

class CardHit(BaseModel):
    card_query: str
    name: str
    set_name: str
    number: str
    rarity: str
    set_series: str
    image_url: str | None = None


class CardValue(BaseModel):
    card_query: str
    # Market anchors, straight from the shared snapshot - competitor ASKING prices.
    active_avg: float | None = None
    active_p25: float | None = None
    active_min: float | None = None
    active_max: float | None = None
    comps: int | None = None
    avg_shipping: float | None = None
    # How much of the raw comp pool survived comp_filter, and why the rest didn't.
    pool_quality: dict | None = None
    snapshot_date: date | None = None
    # TCGdex/TCGPlayer market price. Partial coverage - roughly a third of cards have no
    # match - so it's a cross-check, never the primary number.
    market_price: float | None = None
    # Link to the same eBay search the comps came from, so the pool can be eyeballed.
    # None for hand-priced rows, which never searched anything.
    search_url: str | None = None
    # Condition is reported as a separate, visible adjustment rather than folded into
    # active_avg. The comp pool is an unknown-condition mix (eBay returns "Ungraded" for
    # ~97% of raw cards), and the multiplier ladder is measurably steeper than what the
    # market actually asks - so burying it in one number would hide a real uncertainty
    # at exactly the moment money is being committed.
    # Pokemon species sprite parsed out of the query text. Only consumed for custom
    # free-text searches, which have no catalog card and so no card art. Falls back to
    # Pikachu when nothing parses; None only if the lookup itself failed.
    sprite_url: str | None = None
    condition: str | None = None
    condition_mult: float = 1.0
    condition_known: bool = True
    adjusted_value: float | None = None
    estimated_fees: float | None = None
    estimated_net: float | None = None
    status: str = "ok"  # ok | no_comps | not_found | manual


def _card_hit(card: dict) -> CardHit:
    return CardHit(
        card_query=_fmt_card(card) or "",
        name=card.get("name") or "",
        set_name=card.get("set_name") or "",
        number=card.get("number") or "",
        rarity=card.get("rarity") or "",
        set_series=card.get("set_series") or "",
        image_url=card_image_url(card),
    )


@router.get("/cards/search", response_model=list[CardHit])
def search_cards(
    q: str = Query(..., min_length=1, max_length=80),
    limit: int = Query(20, ge=1, le=SEARCH_LIMIT_MAX),
    user_id: UUID = Depends(get_current_user_id),
):
    """Autocomplete over every printing in the catalog. No eBay call, no DB query."""
    hits = get_card_catalog().search_cards(q, limit=limit)
    return [_card_hit(c) for c in hits]


def _today_snapshot(conn, card_query: str, today: date) -> dict | None:
    row = conn.execute(
        "SELECT card_query, snapshot_date, sample_size, avg_price, min_price, max_price, "
        "p25_price, avg_shipping, pool_quality "
        "FROM active_price_snapshots WHERE card_query = %s "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (card_query,),
    ).fetchone()
    return dict(row) if row else None


def _value_one(card_query: str, condition: str | None, today: date) -> CardValue:
    mult, known = condition_multiplier(condition)
    try:
        sprite = get_sprite_url(card_query)
    except Exception:
        sprite = None

    with get_db() as conn:
        snap = _today_snapshot(conn, card_query, today)

    # Two reasons to spend an eBay call, not one.
    #
    # stale      - nothing from today.
    # unfiltered - a snapshot that carries no pool_quality never went through
    #              comp_filter. Those come from the legacy SQLite ingest, which writes
    #              the same active_price_snapshots row with only six columns and wins
    #              the race on days it runs first. It carries TODAY's date, so a
    #              date check alone accepts it - and it may hold graded slabs,
    #              multi-card lots and wrong prints. Pricing a purchase decision off
    #              that is exactly what this page must not do.
    #
    # force is required for the unfiltered case specifically: research_card_active's
    # own cache check finds that same-day row and would hand straight back the
    # unfiltered snapshot we are trying to replace.
    stale = snap is None or snap.get("snapshot_date") != today
    unfiltered = snap is not None and snap.get("pool_quality") is None
    if stale or unfiltered:
        fresh = research_card_active(card_query, today, force=unfiltered)
        # On failure keep whatever we had: a stale-but-real number beats none, and the
        # response still reports pool_quality=None so the UI can flag it.
        if fresh is not None:
            snap = fresh

    if not snap or snap.get("avg_price") is None:
        return CardValue(
            # Most useful precisely here: "it found nothing" invites checking why.
            card_query=card_query, status="no_comps", sprite_url=sprite,
            search_url=web_search_url(card_query),
            condition=condition, condition_mult=mult, condition_known=known,
        )

    avg = float(snap["avg_price"])
    adjusted = round(avg * mult, 2)
    fees, net = estimate_fees_and_net(adjusted)

    ident = card_identity(card_query)
    market = None
    if ident:
        try:
            market = _lookup_price(
                ident["name"], ident["set_name"], ident["number"],
                "reverseHolofoil" if ident.get("reverse") else "holofoil",
            )
        except Exception:
            market = None

    def _f(key):
        v = snap.get(key)
        return float(v) if v is not None else None

    return CardValue(
        card_query=card_query,
        active_avg=avg,
        active_p25=_f("p25_price"),
        active_min=_f("min_price"),
        active_max=_f("max_price"),
        comps=snap.get("sample_size"),
        avg_shipping=_f("avg_shipping"),
        pool_quality=snap.get("pool_quality"),
        snapshot_date=snap.get("snapshot_date"),
        market_price=market,
        search_url=web_search_url(card_query),
        sprite_url=sprite,
        condition=condition,
        condition_mult=mult,
        condition_known=known,
        adjusted_value=adjusted,
        estimated_fees=fees,
        estimated_net=net,
        status="ok",
    )


@router.get("/card", response_model=CardValue)
def value_card(
    card_query: str = Query(..., min_length=1, max_length=200),
    condition: str | None = Query(None, max_length=40),
    user_id: UUID = Depends(get_current_user_id),
):
    """Value one card. Costs at most one Browse call, then cached for the rest of the day."""
    return _value_one(card_query, condition, datetime.now(timezone.utc).date())


@router.get("/manual", response_model=CardValue)
def value_manual(
    name: str = Query(..., min_length=1, max_length=200),
    price: float = Query(..., ge=0),
    user_id: UUID = Depends(get_current_user_id),
):
    """Value a card the seller priced themselves - no eBay call, no comps, no catalog.

    For anything the market can't be asked about: a card already appraised, a bundle of
    bulk priced as one line, or a listing eBay simply returns nothing usable for.

    The condition multiplier is deliberately NOT applied. A searched card starts from a
    mixed-condition comp average that has to be scaled to the grade in hand; a price the
    seller typed is already the value of the actual card, so scaling it again would
    quietly reduce a number they stated outright.

    Fees still come from estimate_fees_and_net rather than being worked out in the
    browser - it is the same tiered function the Excel pipeline and the suggested-price
    model use, and a second copy in TypeScript is a copy that drifts.
    """
    fees, net = estimate_fees_and_net(price)
    try:
        sprite = get_sprite_url(name)
    except Exception:
        sprite = None
    return CardValue(
        card_query=name.strip(),
        adjusted_value=round(price, 2),
        estimated_fees=fees,
        estimated_net=net,
        sprite_url=sprite,
        condition_mult=1.0,
        status="manual",
    )


class BatchRequest(BaseModel):
    card_queries: list[str]
    condition: str | None = None


@router.post("/batch", response_model=list[CardValue])
def value_batch(body: BatchRequest, user_id: UUID = Depends(get_current_user_id)):
    """Value several cards at once, for pasting in a pile. Capped at MAX_BATCH: each
    uncached card is a live eBay call, and this endpoint runs in a request handler."""
    queries = [q.strip() for q in body.card_queries if q and q.strip()]
    if not queries:
        return []
    if len(queries) > MAX_BATCH:
        raise HTTPException(
            400, f"Too many cards in one request ({len(queries)}); the limit is {MAX_BATCH}. "
                 "Each uncached card costs a live eBay lookup.",
        )
    today = datetime.now(timezone.utc).date()
    # Deduplicate but keep the caller's order - the same card twice is one lookup.
    seen: dict[str, CardValue] = {}
    out: list[CardValue] = []
    for q in queries:
        if q not in seen:
            seen[q] = _value_one(q, body.condition, today)
        out.append(seen[q])
    return out
