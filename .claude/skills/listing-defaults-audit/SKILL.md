---
name: listing-defaults-audit
description: Audit a proposed eBay listing draft against this seller's standard defaults (condition wording, shipping profile, description template, package weight/dimensions, promoted rate, title conventions) before it goes live, and flag anything that will break downstream pricing. Use when reviewing, drafting, or bulk-checking listing fields.
---

# Listing defaults audit

Canonical defaults live in `ebay-defaults-extension/defaults.js` (`DEFAULTS`, with
the allowed alternatives in `PRESETS`). That file is what the Chrome extension
fills into eBay's listing form, so it *is* the standard — read it rather than
trusting a remembered value, and update it if the standard changes.

## Audit checklist

Walk the draft field by field. Report mismatches grouped as **blocking** (will
produce wrong data or wrong pricing) vs. **advisory** (deviates from the norm,
may be deliberate).

### 1. Condition — blocking when it breaks the pricing ladder

The condition string must land in `CONDITION_MULTIPLIER` in
`services/suggested_price.py`, or the pricing model applies multiplier 1.0 and
flags `condition_unknown` — the card gets priced as if Near Mint regardless of
what it actually is.

Recognized: `near mint`, `mint`, `new`, `new with box`, `like new`,
`lightly played`, `moderately played`, `played`, `heavily played`, `damaged`,
`poor` (matched case-insensitively).

Note the trap: the extension's default is **"Near Mint or better"**, which is
*not* a key in that map. It resolves to 1.0 anyway — the same value Near Mint
would get — so the price is right, but the row carries a `condition_unknown`
flag. Flag this as advisory, not a bug to "fix" by changing the price.

Also check the **title**: `TITLE_CONDITION_MAP` in `trading_api.py` parses
`NM / LP / MP / HP / DMG` and their long forms out of the title, and
`resolve_condition` prefers the title over the API's value. A title saying "LP"
on a listing whose condition field says Near Mint will be priced as Lightly
Played (0.80x). That contradiction is **blocking**.

### 2. Title — blocking when it suppresses pricing

`EXCLUDED_TITLE_KEYWORDS` in `suggested_price.py` (`holo bleed`, `swirl`,
`miscut`, `error`) cause the model to **decline to suggest a price at all**
(`status: "excluded"`). That is intentional — defect/novelty variants trade on
the defect, and the comp pool of ordinary copies says nothing about their value.

If a draft title contains one of these, say so up front: this listing will never
get an automatic price and needs manual pricing forever.

### 3. Shipping profile — blocking when unmapped

The profile name must exist in `SHIPPING_PRICE_MAP` in
`ebaypricer/listing_economics.py`, which maps it to an assumed cost:

| Profile (lowercased) | Assumed cost |
|---|---|
| `free ebay standard` | $0 |
| `ebay standard envelope` | $0.78 |
| `ground advantage` | $5 |
| `free ground advantage` | $0 |

Anything else silently maps to **$0**, overstating net proceeds on every
downstream calculation. Default is `Free ebay standard`.

Worth knowing: on a free-shipping profile the *buyer* pays $0 but we still pay
postage, which is why `net_floor()` adds `ASSUMED_SHIP_COST` ($0.78, the eBay
Standard Envelope rate) when `shipping_charge` is zero.

### 4. Format

Default `Buy It Now`. Auction is a real deviation, not a typo — the comp pool is
pinned to `FIXED_PRICE` in `browse_api.py`, so an auction listing is not
comparable to the comps the pricing model uses. Flag as advisory with that
reason.

### 5. Package weight and dimensions

Defaults: **0 lb 1 oz**, **11 × 6 × 1 in** (a single card in a penny sleeve and
top loader in a rigid mailer). A draft departing from these usually means a
multi-card lot or a sealed product, which also invalidates single-card comps —
worth calling out together.

### 6. Promoted rate

Default **2%**, which matches the base of `compute_target_bid` in
`marketing_api.py` (2.0 + 1.0 per 10 unsold days, capped). Starting above 2%
means `auto_boost_promotion` will not raise it until staleness catches up to
whatever it was set to.

### 7. Description

Default template key is `reg`; the body is the multi-line string in `DEFAULTS.description`
(penny sleeve + top loader, ships within 1 business day, smoke free home, see
photos for condition). Check the claims are still true for this listing — "see
photos for condition" on a draft with no condition photos is a real problem.

### 8. Custom label / SKU

`PRESETS.customLabel` offers the grade vocabulary (`PSA 10`…`Raw`, `Ungraded`);
`DEFAULTS.customLabel` is empty. Note that a graded custom label contradicts the
raw-only comp pool — comps exclude `-PSA -BGS -CGC -SGC -graded -slab`, so a
graded card cannot be priced by this model.

## Output format

Report as a short table of `field | draft value | expected | severity`, then a
one-line verdict. Do not silently normalize a draft to the defaults — the point
is to surface deviations for a human decision, since plenty of them are
deliberate.
