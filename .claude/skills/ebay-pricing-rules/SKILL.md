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
anchors -> staleness/rank blend -> condition multiplier -> watcher pull -> guardrails -> rounding
```

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
`status` of `cooldown` / `excluded` / `thin_comps` / `no_comps`. Do not fill these
with a fallback number — a wrong suggestion is worse than none, and the status is
what the UI shows the user.

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

**The comp pool is raw, ungraded, Buy It Now only.** `browse_api.py` pins
`BUYING_OPTIONS = "FIXED_PRICE"` and appends `EXCLUDED_TERMS`
(`-PSA -BGS -CGC -SGC -graded -slab`) to every query. Comps are therefore not
comparable to graded-slab pricing, and the model must never be pointed at a graded
listing and expected to be right.

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
- Best Offer thresholds are pinned to `OFFER_THRESHOLD_PCT` (0.9) of the new price
  in `routers/active.py` — auto-accept above, auto-decline below.
- Applying a price is a live marketplace write: see the `ebay-listing-dry-run` skill.
