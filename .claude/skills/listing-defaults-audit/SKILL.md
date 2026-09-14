---
name: listing-defaults-audit
description: Audit a proposed eBay listing draft against this seller's standard defaults (condition wording, shipping profile, description template, package weight/dimensions, promoted rate, title conventions) before it goes live, and flag anything that will break downstream pricing. Use when reviewing, drafting, or bulk-checking listing fields.
---

# Listing defaults audit

Canonical defaults live in `ebay-defaults-extension/defaults.js` (`DEFAULTS`, with
the allowed alternatives in `PRESETS`). That file is what the Chrome extension
fills into eBay's listing form, so it *is* the standard — read it rather than
trusting a remembered value, and update it if the standard changes.

**There is a second copy.** `dashboard/backend/services/listing_csv.py` restates the
same defaults in eBay File Exchange's vocabulary, for the bulk-upload CSV the
Inventory page builds (`POST /inventory/listing-csv`). It is a copy rather than a
parse because `defaults.js` is JavaScript and its description is an array joined at
runtime. So changing a default means changing **both**, and the two speak different
dialects of the same thing:

| defaults.js (form) | listing_csv.py (CSV) |
|---|---|
| `format: "Buy It Now"` | `FORMAT = "FixedPrice"` |
| `description` (plain text, newline-separated) | `DESCRIPTION_HTML` (eBay's field is HTML) |
| `packageWeight`, `dimensions` | `WEIGHT_MAJOR`/`WEIGHT_MINOR`, `PACKAGE_*` |
| `shippingPolicy` | `DEFAULT_SHIPPING_PROFILE` (must stay a `SHIPPING_PRICE_MAP` key) |
| `condition: "Near Mint or better"` | `EBAY_CARD_CONDITION`, keyed on the app's grades |
| `promotedRate: 2` | **nothing** — see below |

A third consumer shares those defaults: `services/prefill_template.py`, which fills
eBay's prefill template for the round-trip flow. It holds no defaults of its own —
title, category and aspects all come from `listing_csv` — so auditing a prefill draft
is auditing the same values, minus price, format, duration, policies and description,
which that file has no columns for.

The item location and the three business policy *names* are not in either file —
they are per-user account facts, stored in `listing_defaults` (migration 0015) and
edited on the Settings page. When auditing a draft, `shipping_profile` there is the
one to check against `SHIPPING_PRICE_MAP`.

Two `DEFAULTS` fields deliberately have no CSV counterpart. `promotedRate` is absent
because a rate baked into a fifty-row bulk upload is exactly the automatic ad spend
the `auto_boost_promotion` removal exists to prevent; Best Offer is absent for the
same reason `revise_best_offer_thresholds` was deleted. Do not add either.

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
`marketing_api.py` (2.0 + 1.0 per 10 unsold days, capped). Nothing raises the
rate on its own any more — `auto_boost_promotion` was taken out of the pipeline
— so whatever is set at listing time is what the listing keeps until someone
deliberately boosts it.

### 7. Description

Default template key is `reg`; the body is the multi-line string in `DEFAULTS.description`
(KLINKSUMMER promo code, combine-orders note, the tiered shipping bullets, and the
Klink TCG sign-off). Check the claims are still true for this listing.

Two that go stale rather than being wrong-on-arrival: the **promo code** is seasonal
and outlives the season unless someone edits it, and the **shipping bullets state a
$20 threshold** — cards under $20 by eBay Standard Envelope, $20 and over by Ground
Advantage in a bubble mailer. A draft whose price sits near that line, or whose
shipping policy doesn't match the side it falls on, is describing a service it won't
get. The CSV exports carry one shipping policy for the whole batch (`shipping_profile`
on Settings), so a mixed-price batch will contradict this text for some of its rows —
worth calling out as advisory when it happens.

`reg` is a key the **Chrome extension** uses to pick a template in eBay's listing
form. There is **no CSV column that references a saved description template by name**
(verified against eBay's uploadable-templates docs: the draft template's only
description field is `Description`, and File Exchange's is `*Description`), so
`listing_csv.DESCRIPTION_HTML` inlines the same body as HTML instead. Changing the
description means changing both.

### 8. Custom label / SKU

`PRESETS.customLabel` offers the grade vocabulary (`PSA 10`…`Raw`, `Ungraded`);
`DEFAULTS.customLabel` is empty. Note that a graded custom label contradicts the
raw-only comp pool — comps exclude `-PSA -BGS -CGC -SGC -graded -slab`, so a
graded card cannot be priced by this model.

The listing CSV ignores that vocabulary and puts the **lot SKU** in `CustomLabel`
instead (`L0030`, `L0041`, …), because `routers/lots.py` groups every sold order and
active listing by exactly that string — a listing created without it never joins the
lot it came out of. Treat a missing SKU on a draft as advisory: the listing works,
but its money will never reach a lot's P&L. Both file builders do this, and the
prefill one keeps it even though eBay recommends a unique per-row label there for
correlating results — lot attribution is the stronger claim, and rows correlate by
title, which is unique per card anyway.

## Output format

Report as a short table of `field | draft value | expected | severity`, then a
one-line verdict. Do not silently normalize a draft to the defaults — the point
is to surface deviations for a human decision, since plenty of them are
deliberate.
