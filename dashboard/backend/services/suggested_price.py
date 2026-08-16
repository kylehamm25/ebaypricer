"""
Suggested price model (staleness-driven).

One canonical, server-side pricing suggestion per active listing. Replaces the old
client-side `computeRecommendedPrice`, which lived in the frontend and was called
with different inputs on the list page vs. the detail page - producing two different
"suggested" numbers for the same listing.

The model in one sentence: price a fresh listing near what competitors are asking,
and the longer it sits unsold, the closer to the competitive floor it gets - adjusted
for card condition, then clamped by guardrails.

    anchors -> staleness/rank blend -> condition multiplier -> shipping adjustment
    -> watcher pull -> guardrails -> rounding

Everything here is pure: no DB, no network, no clock. `compute_suggested_price` takes
plain values and returns a `Suggestion` carrying the price plus every intermediate,
so the caller can persist the reasoning (see active_listings.suggested_price_basis)
and the UI can explain itself.

Why condition is a multiplier and not a comp filter: our own listings carry real TCG
grades (resolve_condition in trading_api.py), but competitor listings do not - eBay's
Browse API returns a generic condition ("Ungraded"/"New"/"Used") for raw cards, so the
comp pool is an unknown-condition mix and cannot be filtered to match. Scaling by
grade is the only mechanism available.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ebaypricer.listing_economics import estimate_fees_and_net

# --- Staleness ramp -------------------------------------------------------------
# Below GRACE a listing is priced for margin; at/after FULL it sits at the
# competitive floor. Chosen against the real age distribution of this inventory
# (most listings are under 30 days, with a long tail past 180).
STALENESS_GRACE_DAYS = 30
STALENESS_FULL_DAYS = 180

# --- Search rank (secondary) ----------------------------------------------------
# Same thresholds the old frontend model used. Deliberately a minority share: the
# direction of this signal is arguable (poor rank might mean "cut to get seen", but
# good rank + no sale arguably means the price is the problem), so it nudges rather
# than drives. RANK_SHARE = 0.0 disables it entirely.
GOOD_RANK = 10
POOR_RANK = 40
RANK_SHARE = 0.20

# --- Condition ------------------------------------------------------------------
# Reuses the ladder that has been sitting unused in scripts/avg_active_price.py,
# extended for the non-TCG values eBay's ConditionDisplayName can return.
# Unmapped/blank -> 1.0: the comp pool is itself a mixed-condition bag, so guessing a
# haircut is worse than applying none; the staleness ramp still corrects a genuinely
# overpriced card.
CONDITION_MULTIPLIER = {
    "near mint": 1.00,
    "mint": 1.00,
    "new": 1.00,
    "new with box": 1.00,
    "like new": 1.00,
    "lightly played": 0.80,
    "moderately played": 0.60,
    "played": 0.60,
    "heavily played": 0.50,
    "damaged": 0.35,
    "poor": 0.35,
}

# --- Reprice cooldown -----------------------------------------------------------
# After a price change is applied, this listing gets no new suggestion for this many
# days. A price needs time to prove itself: the comp pool barely moves day to day, so
# without a cooldown the model re-proposes essentially the same edit on every run, and
# the change cap turns one intended reprice into a slow ratchet of daily nudges. The
# staleness ramp also keeps climbing while a listing sits, so an untouched listing's
# suggestion drifts down on its own - a listing repriced yesterday would be asked to
# move again today for no new reason.
#
# Fed by price_change_log (see db/migrations/0005), which records only changes that
# eBay actually accepted - a rejected revision must not start a cooldown.
REPRICE_COOLDOWN_DAYS = 5

# --- Sample size ----------------------------------------------------------------
MIN_COMPS = 3           # below this we decline to suggest at all
LOW_CONFIDENCE_COMPS = 6  # below this we suggest, but hedge toward the margin end

# --- Watcher demand ---------------------------------------------------------------
# Watchers are a direct demand signal this listing already has, independent of the
# comp pool - a heavily-watched card shouldn't be repriced (up or down) as aggressively
# as the staleness/rank/condition math alone would suggest, since it's already proving
# itself. Pulls the target back toward current_price; saturates at WATCHER_SATURATION
# so one viral outlier doesn't fully freeze the price.
WATCHER_SATURATION = 5
MAX_WATCHER_PULL = 0.6

# --- Guardrails -----------------------------------------------------------------
# Change cap: a suggestion is a next step, not a destination. Tiered like
# auto_boost_promotion's max_bid so a $1 card can still move and a $200 one cannot
# swing wildly in a single step.
#
# 25% is a deliberate balance. Much tighter (15%) and the cap dominates every other
# input - a Moderately Played card and a Near Mint one both come out at the cap
# boundary, making the condition ladder invisible in the output. Looser and a single
# odd comp pool can propose a drastic reprice. Where the cap does bind, the basis
# records `pre_guardrail` so the UI can show "step to $2.98 (target $1.32)".
#
# CHANGE_CAP_MAX is a hard ceiling regardless of price - no suggestion moves a
# listing by more than $2 in one step, even a $200 card.
CHANGE_CAP_PCT = 0.25
CHANGE_CAP_MIN = 0.25
CHANGE_CAP_MAX = 2.00

ABSOLUTE_PRICE_FLOOR = 0.99

# Net floor. NOTE: this repo has no cost basis - no COGS column, and shipping_charge
# is what the *buyer* pays (0 on free-shipping listings, where we actually absorb the
# label cost). So "never sell at a loss" is not computable; these are deliberate
# proxies for it. Revisit if a real cost_basis column is ever added.
MIN_NET_PROCEEDS = 1.00
ASSUMED_SHIP_COST = 0.78  # eBay Standard Envelope rate, applied when buyer pays $0

# --- Title exclusions ------------------------------------------------------------
# Print-defect / novelty variants (holo bleed, swirl, miscut, error) trade on the
# defect itself, not on the card's normal market - the comp pool (ordinary copies of
# the same card) has nothing to say about what one of these is worth, so we decline
# to suggest a price rather than silently pricing a defect card off normal comps.
EXCLUDED_TITLE_KEYWORDS = ("holo bleed", "swirl", "miscut", "error")


def excluded_title_keyword(title: str | None) -> str | None:
    """Returns the matched keyword if `title` names a print-defect/novelty variant
    that suggestions are declined for, else None."""
    key = (title or "").lower()
    for kw in EXCLUDED_TITLE_KEYWORDS:
        if kw in key:
            return kw
    return None


# --- Rounding -------------------------------------------------------------------
# Card prices conventionally end .49/.99; matches how this inventory is already
# priced. Set to () to disable. Below $2 the endings are too coarse, so snap to 5c.
PSYCH_ENDINGS = (0.49, 0.99)
PSYCH_MIN_PRICE = 2.00
SUB_PSYCH_STEP = 0.05


@dataclass
class Suggestion:
    """Result of the model. `price is None` means we declined to suggest (see status)."""
    price: float | None
    status: str  # "ok" | "cooldown" | "excluded" | "thin_comps" | "no_comps"
    basis: dict = field(default_factory=dict)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def condition_multiplier(condition: str | None) -> tuple[float, bool]:
    """Returns (multiplier, known). `known` is False for blank/unrecognized grades,
    which callers surface as a flag so an unmapped condition string is visible rather
    than silently treated as Near Mint."""
    key = (condition or "").strip().lower()
    if key in CONDITION_MULTIPLIER:
        return CONDITION_MULTIPLIER[key], True
    return 1.0, False


def net_floor(shipping_charge: float | None) -> float:
    """Lowest price that still clears MIN_NET_PROCEEDS after eBay/payment fees, plus
    assumed postage when the buyer is charged nothing for shipping.

    estimate_fees_and_net is a step function (65%/70%/73% of price at the $2 and $5
    boundaries), so this walks the tiers rather than inverting it algebraically - the
    naive inversion can land outside the tier whose multiplier it used."""
    needed = MIN_NET_PROCEEDS
    if not shipping_charge:
        needed += ASSUMED_SHIP_COST

    # (tier upper bound, net multiplier) mirroring listing_economics.estimate_fees_and_net
    for upper, mult in ((2.0, 0.65), (5.0, 0.70), (float("inf"), 0.73)):
        candidate = needed / mult
        if candidate <= upper:
            return round(candidate, 2)
    return round(needed / 0.73, 2)


def psych_round(price: float, direction: str = "nearest") -> float:
    """Snap to a conventional price ending. `direction="up"` is used after a floor
    clamp so rounding can never push back below the floor we just enforced."""
    if price < PSYCH_MIN_PRICE or not PSYCH_ENDINGS:
        stepped = price / SUB_PSYCH_STEP
        stepped = -(-stepped // 1) if direction == "up" else round(stepped)
        return round(stepped * SUB_PSYCH_STEP, 2)

    whole = int(price)
    candidates = sorted(
        {round(w + e, 2) for w in (whole - 1, whole, whole + 1) for e in PSYCH_ENDINGS if w >= 0}
    )
    if direction == "up":
        above = [c for c in candidates if c >= price - 1e-9]
        return above[0] if above else round(price, 2)
    return min(candidates, key=lambda c: (abs(c - price), c))


def compute_suggested_price(
    *,
    current_price: float | None,
    anchor_avg: float | None,
    anchor_floor: float | None,
    comps: int | None,
    days_listed: int | None,
    rank: int | None,
    condition: str | None,
    shipping_charge: float | None = None,
    comp_avg_shipping: float | None = None,
    watchers: int | None = None,
    days_since_price_change: float | None = None,
) -> Suggestion:
    """Suggest a price for one listing.

    anchor_avg   - mean competitor asking price (the margin end)
    anchor_floor - 25th-percentile competitor price (the competitive end)
    shipping_charge   - what WE charge the buyer for shipping this listing.
    comp_avg_shipping - mean shipping cost among today's comp pool, or None if no
                   comp reported one. Both anchors above are competitor ITEM price,
                   same as current_price is ours - comparing those alone ignores
                   shipping, so a $12 free-shipping listing looks overpriced next to
                   a $10-item/$5-shipping comp that's actually $3 more expensive
                   landed. See the shipping-adjustment step below.
    days_since_price_change - age of the last applied price change, or None if this
                   listing has never been repriced through the app. Keeps this module
                   clock-free: the caller reads price_change_log and does the
                   subtraction, we only compare against REPRICE_COOLDOWN_DAYS.
    """
    basis: dict = {"v": 1}
    flags: list[str] = []

    # Checked before the comp gates so the reason surfaced is the cooldown, which is
    # the actionable one ("we changed this 2 days ago"), not an incidental thin-comps.
    if days_since_price_change is not None and days_since_price_change < REPRICE_COOLDOWN_DAYS:
        return Suggestion(None, "cooldown", {
            **basis,
            "status": "cooldown",
            "days_since_price_change": round(days_since_price_change, 2),
            "cooldown_days": REPRICE_COOLDOWN_DAYS,
        })

    if anchor_avg is None or anchor_floor is None or not comps:
        return Suggestion(None, "no_comps", {**basis, "status": "no_comps", "comps": comps or 0})
    if comps < MIN_COMPS:
        return Suggestion(None, "thin_comps", {**basis, "status": "thin_comps", "comps": comps})

    anchor_avg = float(anchor_avg)
    anchor_floor = float(anchor_floor)

    # 1. Staleness weight (primary driver)
    if days_listed is None:
        w_days = 0.0  # unknown age is treated as fresh; never punish missing data
        flags.append("no_days_listed")
    else:
        w_days = _clamp(
            (days_listed - STALENESS_GRACE_DAYS) / (STALENESS_FULL_DAYS - STALENESS_GRACE_DAYS),
            0.0, 1.0,
        )

    # 2. Rank nudge (secondary). Unknown rank contributes nothing rather than pulling
    #    toward a neutral midpoint, which is what the old model did.
    if rank is None:
        w = w_days
        w_rank = None
        flags.append("no_rank")
    else:
        w_rank = _clamp((rank - GOOD_RANK) / (POOR_RANK - GOOD_RANK), 0.0, 1.0)
        w = (1 - RANK_SHARE) * w_days + RANK_SHARE * w_rank

    # Thin-ish samples: we are less sure where the floor really is, so don't chase it.
    if comps < LOW_CONFIDENCE_COMPS:
        w *= 0.5
        flags.append("low_confidence")

    # 3. Position within the competitive band
    blend = anchor_avg * (1 - w) + anchor_floor * w

    # 4. Condition
    mult, known = condition_multiplier(condition)
    if not known:
        flags.append("condition_unknown")
    target = blend * mult

    # 4.4 Shipping-adjusted positioning. blend/target above are pegged to competitor
    # ITEM price; shift by the gap between what comps charge for shipping on average
    # and what we charge, so the target reflects total landed price instead. We
    # charge more than average -> target comes down (our item price needs to be
    # cheaper to match their total); we charge less/free -> target goes up. Skipped
    # (0.0) when no comp reported a shipping cost - "no data" must not be treated as
    # "comps ship free", which would push every target up.
    shipping_adjustment = 0.0
    if comp_avg_shipping is not None:
        shipping_adjustment = float(comp_avg_shipping) - float(shipping_charge or 0)
        target += shipping_adjustment

    # 4.5 Watcher demand pull. A live demand signal the comp pool can't see - pulls the
    # target back toward the current price rather than pushing it further, since the
    # direction (up or down) the comps/staleness math wants to move is orthogonal to
    # whether this specific listing is already working.
    watcher_pull = 0.0
    if current_price and watchers:
        watcher_pull = _clamp(watchers / WATCHER_SATURATION, 0.0, MAX_WATCHER_PULL)
        if watcher_pull > 0:
            target = target * (1 - watcher_pull) + float(current_price) * watcher_pull

    pre_guardrail = round(target, 2)

    # 5/6/7. Guardrails, then rounding.
    #
    # Clamp order: the change cap pulls toward the current price, so it must run
    # BEFORE the lower bounds - otherwise an already-underpriced listing would have
    # its suggestion capped back down below the floor we just enforced.
    #
    # Rounding runs LAST so the number we emit actually lands on a conventional price
    # ending. Rounding before clamping means the clamp is the final operation and the
    # output is an arbitrary boundary value like $2.98. Rounding can nudge up to ~$0.50
    # back outside the cap; that slack is accepted (and allowed for in the verification
    # queries), but never below the hard floor - hence the round-up retry.
    clamps: list[str] = []

    if current_price:
        cap = _clamp(CHANGE_CAP_PCT * float(current_price), CHANGE_CAP_MIN, CHANGE_CAP_MAX)
        capped = _clamp(target, float(current_price) - cap, float(current_price) + cap)
        if abs(capped - target) > 1e-9:
            clamps.append("change_cap")
            target = capped

    lower = max(net_floor(shipping_charge), ABSOLUTE_PRICE_FLOOR)
    if target < lower:
        clamps.append("net_floor" if lower > ABSOLUTE_PRICE_FLOOR else "absolute_floor")
        target = lower

    target = psych_round(target)
    if target < lower:
        target = psych_round(lower, direction="up")

    basis.update({
        "status": "ok",
        "anchor_avg": round(anchor_avg, 2),
        "anchor_floor": round(anchor_floor, 2),
        "comps": comps,
        "days_listed": days_listed,
        "rank": rank,
        "w_days": round(w_days, 3),
        "w_rank": round(w_rank, 3) if w_rank is not None else None,
        "w": round(w, 3),
        "condition": condition or "",
        "condition_mult": mult,
        "shipping_charge": shipping_charge,
        "comp_avg_shipping": comp_avg_shipping,
        "shipping_adjustment": round(shipping_adjustment, 2),
        "watchers": watchers,
        "watcher_pull": round(watcher_pull, 3),
        "pre_guardrail": pre_guardrail,
        "clamps": clamps,
        "flags": flags,
    })
    return Suggestion(round(target, 2), "ok", basis)
