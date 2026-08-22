---
name: ebay-listing-dry-run
description: Mandatory preview-then-confirm protocol for anything that mutates live eBay state - price revisions, Best Offer thresholds, promoted-listing ad rates, creating ads. Load before running the pipeline, calling a revise/bulk-price endpoint, or writing code that issues a marketplace write. These changes cost money and are not cleanly reversible.
---

# eBay live-write dry run

Every write in this repo lands on a **live marketplace with real buyers and real
money**. There is no sandbox wired up. A bad price revision can sell inventory
below cost before anyone notices; a bad ad-rate change spends money immediately.
Treat all of it as production.

## The rule

**Never issue a marketplace write without first showing the exact set of changes
and getting explicit confirmation.** Not "I'm going to reprice some listings" —
the actual item IDs, the old value, the new value, and the count.

## Inventory of live-mutating paths

Know these on sight. Anything reaching one of them is a live write.

**Trading API — `ebaypricer/trading_api.py`**
- `revise_item_price` → `ReviseFixedPriceItem`, changes a listing's price. The only
  write here. Price and nothing else — Best Offer thresholds are never touched.

**Marketing API — `ebaypricer/marketing_api.py`**
- `bulk_update_bids` → up to 500 ad rates in one call (**spends money**)
- `create_ad` → enrolls a listing into a promoted campaign

**HTTP endpoints — `dashboard/backend/routers/`**
- `POST /api/v1/active/item/{item_id}/price` — applies immediately, no preview
- `POST /api/v1/active/bulk-price` — up to `MAX_BULK_ITEMS` (100) per request
- `POST /api/v1/ebay/promotion-boost`

**Scripts**
- `scripts/auto_boost_promotion.py` — raises real ad rates
- `scripts/main.py` — runs the above as its final stage

## Where a real dry run already exists

`scripts/main.py` and `scripts/auto_boost_promotion.py` both accept
`--dry-run`, which prints the intended promotion changes without applying them.
**Always run with `--dry-run` first**, show the output, then re-run without it
only after confirmation.

A `PreToolUse` hook (`.claude/hooks/guard-shell-commands.ps1`) already intercepts
these two scripts when `--dry-run` is absent and asks for approval. Treat that
prompt as a backstop, not as the review — do the preview yourself first.

## Where no dry run exists — you must construct one

The dashboard endpoints apply immediately; the review step lives in the UI's
bulk flow, not in the API. When driving them programmatically:

1. **Enumerate** the affected rows first with a read-only query against
   `active_listings` (item_id, title, current `price`, `suggested_price`,
   `suggested_price_basis`).
2. **Diff** — render old → new per item, plus the total count and the largest
   single move. Call out anything where the basis shows `clamps` containing
   `change_cap` (the model wanted to move further) or a `status` other than `ok`.
3. **Confirm** explicitly with the user.
4. **Apply**, in batches within the 100-item cap.
5. **Verify** against `price_change_log`, which records only revisions eBay
   actually accepted, and reconcile per-item results — the bulk endpoint attempts
   each item independently and returns `ok` / `error` per item. (There was once a
   `partial` for a price that landed while its Best Offer thresholds didn't; with a
   price-only revision there is no half-applied state left.)

## Best Offer is not ours to touch

Repricing changes the **price only**. Auto-accept and minimum-offer thresholds are
the seller's own listing settings and are deliberately left alone. `OFFER_THRESHOLD_PCT`,
`revise_best_offer_thresholds` and `revise_price_with_best_offer` were all removed;
do not reintroduce them or derive a threshold from a price.

Kept only because it would bite anyone who ever adds a *separate, deliberate*
offer-threshold action: price and thresholds **can never move in one call**. eBay
validates each side against what is *currently live* on the listing, never against
the other new value in the same request.

- Cutting the price while the old, higher auto-decline is still live →
  *"Auto decline amount cannot be greater than or equal to the Buy It Now price"*.
- Raising thresholds before the higher price is live → same class of rejection.

The fix is two sequenced calls moving whichever side gains slack first: **thresholds
down before a price cut, price up before a threshold raise.** Getting the order wrong
is rejected outright, not silently ignored.

## Failure handling

- `EbayReviseError` carries eBay's own message, filtered to `Error`-severity
  entries — a failed revision usually also returns a business-policies advisory at
  warning severity that makes the real cause unreadable. Surface the message
  verbatim; do not retry blindly.
- Common legitimate rejections: the item already ended, or the price is outside
  the range eBay permits for a revision.
- Writes to `price_change_log` deliberately never fail the revision — the price is
  already live on eBay by then, so losing history must not roll back the record of
  it. A missing log row does not mean the change did not happen.
- `revise_item_price` needs the `sell.inventory` scope — **not** `.readonly`.

## Reversibility

Price changes are reversible only by issuing another revision (which starts a new
`REPRICE_COOLDOWN_DAYS` window and is itself a live write). Ad-rate spend and any
sale that completes at the wrong price are **not reversible at all**. This is why
preview is mandatory rather than merely polite.
