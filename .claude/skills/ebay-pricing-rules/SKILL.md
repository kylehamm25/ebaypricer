---
name: ebay-pricing-rules
description: The pricing model for active eBay listings - how a suggested price is derived, which guardrails apply, and what must never be reintroduced. Load before changing pricing logic, tuning constants, explaining why a listing got the price it did, adding a pricing input, or writing anything that computes or displays a suggested/recommended price.
---

# eBay pricing rules

## The model lives in code, not here

`dashboard/backend/services/suggested_price.py` is the single source of truth.
Read it before changing anything. Every tuning constant is defined at the top of
that file with a comment explaining why it holds its value — this skill does not
restate the numbers, because a copy here would drift and you would tune the copy.

The model in one line: **price a fresh listing near what competitors are asking,
and the longer it sits unsold, the closer to the competitive floor it gets —
adjusted for condition, then clamped.**

```
anchors -> comp sanity gate -> staleness/rank blend -> condition multiplier
-> shipping adjustment -> watcher pull -> guardrails -> rounding
```

## The inputs beyond the comp anchors

- **Shipping adjustment** repositions the target on *total landed price* (item +
  shipping): the anchors and our own price are both item-only, so a free-shipping
  listing looks overpriced next to a cheaper item that charges for postage. Uses
  `comp_avg_shipping`, the mean shipping cost across today's comp pool (migration
  0007). `None` means "no comp reported one" and must not be read as "comps ship
  free" — that would push every target up.
- **Watcher pull** dampens the move for a listing that already has demand, pulling
  the target back toward the current price and saturating at `WATCHER_SATURATION`
  so one viral outlier can't freeze the price outright.
- **`excluded_title_keyword()`** declines outright (status `excluded`) for
  print-defect/novelty titles — those trade on the defect, and the ordinary comp
  pool says nothing about their value. Same list `comp_filter` uses on comps.
- **`price_change_log`** (migration 0005) records only price changes eBay actually
  accepted, and drives the reprice cooldown.

## Invariants — do not break these

**`compute_suggested_price` is pure.** No DB, no network, no clock. Clock-derived
inputs (`days_since_price_change`) are computed by the caller and passed in. This
is what makes the model testable and its output explainable. If you need "now"
inside it, you are solving the problem in the wrong place.

**One suggestion, computed server-side.** This model replaced a client-side
`computeRecommendedPrice` that ran with different inputs on the list page vs. the
detail page and produced two different numbers for the same listing. Both pages
now read the stored `suggested_price` through the same `_SELECT` in
`routers/active.py`. Never compute a price in the frontend.

**Persist the reasoning.** Every run writes `suggested_price_basis` (a JSON dict
of every intermediate) alongside the price. The UI explains itself from that. A
change that adds an input must add it to the basis too.

**Clamp order is load-bearing.** Change cap runs *before* the lower bounds, or an
already-underpriced listing gets capped back below the floor just enforced.
Rounding runs *last*, or the emitted number is an arbitrary clamp boundary like
$2.98 instead of a real price ending. There is a round-up retry so rounding can
never re-cross the hard floor.

**Declining to suggest is a valid, meaningful output.** `price is None` with a
`status` of `cooldown` / `excluded` / `thin_comps` / `no_comps` / `comp_mismatch`.
Do not fill these with a fallback number — a wrong suggestion is worse than none,
and the status is what the UI shows the user.

**A comp pool wildly out of line with our own price is not usable.** Beyond
`MAX_ANCHOR_RATIO` in either direction, Browse matched the card name but found a
different product — damage, a novelty print, a promo stamp, something the pool
cannot see — so the anchor is meaningless and the status is `comp_mismatch`. This
deliberately trusts our own price as the reference, which means a genuinely
mispriced listing gets no suggestion; that is the safe direction. Read the constant's
comment before touching it: it was measured against the real ratio distribution,
not chosen.

## The parts that surprise people

**Sold comps do not come from eBay.** eBay's Browse API has no sold search; it
silently ignores the `soldDate` filter and returns ordinary active listings.
Sold-side research uses TCGdex/TCGPlayer market price via
`ebaypricer.cards.lookup_market_price`, which yields one price point, so those
snapshots are `sample_size=1` rather than an aggregate. See the note at the top of
`browse_api.py`. Do not recreate a "sold" search against Browse.

**Condition is a multiplier, not a comp filter.** Our listings carry real TCG
grades (`resolve_condition` in `trading_api.py`), but competitor listings do not —
Browse returns a generic condition for raw cards, so the comp pool is an
unknown-condition mix that cannot be filtered to match. Scaling by grade is the
only mechanism available. An unmapped condition string yields multiplier 1.0 and a
`condition_unknown` flag rather than a guessed haircut.

**Our own listings are excluded from the comp pool.** Without that, cutting a
price feeds back as a lower "competitor" price on the next run and ratchets
downward. If self-exclusion leaves fewer than 3 comps, the unfiltered pool is used
instead — a band off 1–2 comps is worse than a slightly self-inflected one.

**The comp pool is raw, ungraded, English, single-card, Buy It Now only — and that
takes two stages.** `browse_api.py` constrains the search itself: `BUYING_OPTIONS =
"FIXED_PRICE"`, `CARD_CATEGORY_ID` (183454, CCG Individual Cards — verified against
live results, not assumed), and `EXCLUDED_TERMS` negative keywords. But negative
keywords only see the title, and eBay returns plenty that the query cannot exclude,
so `comp_filter.py` screens the *results* before any aggregate is computed:

- **hard** drops (never restored) — graded slabs (eBay's own `condition` field is the
  reliable signal; a slab titled "TAG 9 - 936 - MINT" contains none of the negative
  keywords), multi-card lots, print-defect one-offs, and foreign-market or
  non-English prints.
- **soft** drops (restored together if the pool falls below `MIN_FILTERED_COMPS`) —
  name mismatch, card-number mismatch, reverse-holo mismatch, Shadowless/1st Edition.

Comps are therefore not comparable to graded-slab pricing, and the model must never
be pointed at a graded listing and expected to be right. Every run records what it
dropped and why in `active_price_snapshots.pool_quality`; check that column before
concluding a suggestion is wrong, and note `soft_restored: true`, which marks a pool
whose anchors knowingly include comps we would rather have dropped.

**Add contamination rules to `comp_filter.py`, not to the aggregation code.** It is
pure (no DB, no network, no IO — the card's identity is resolved by
`cards.card_identity()` and passed in), so a new rule is testable on plain dicts.

**The floor anchor is p25, not min.** Cheapest-listing chasing tracks junk
listings; the 25th percentile is "cheaper than 75% of the market". Falls back to
`min_price` only for rows researched before `p25_price` existed.

**The reprice cooldown exists because the change cap ratchets.** Without it the
model re-proposes essentially the same edit every run and one intended reprice
becomes a slow daily drift. Fed by `price_change_log`, which records only changes
eBay *accepted* — a rejected revision must not start a cooldown.

## There is no cost basis

This repo has **no COGS column**, and `shipping_charge` is what the *buyer* pays
(0 on free-shipping listings, where we absorb the label cost). So "never sell at a
loss" and any true margin target are **not computable** here. `MIN_NET_PROCEEDS`
and `ASSUMED_SHIP_COST` are deliberate proxies for it, and `net_floor()` walks the
fee tiers rather than inverting them, because `estimate_fees_and_net` is a step
function and the naive inversion lands outside its own tier.

If asked for a margin target, say this rather than inventing one. Adding a real
`cost_basis` column is the prerequisite, and it would let `net_floor` become a
true break-even floor.

## Related

- `ebaypricer/listing_economics.py` — tiered fee/net estimation, shared with the
  Excel pipeline so both paths agree.
- Best Offer is **out of scope for pricing**. Applying a price changes the price and
  nothing else; auto-accept and minimum-offer thresholds belong to the seller and are
  left untouched. `OFFER_THRESHOLD_PCT` (which pinned both to 0.9 of the new price)
  and the two `revise_*best_offer*` helpers were removed. Never derive a threshold
  from a suggested price.
- Applying a price is a live marketplace write: see the `ebay-listing-dry-run` skill.
