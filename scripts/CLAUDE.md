# Legacy Excel pipeline (`scripts/`)

Moved out of the root CLAUDE.md so it loads only when you are actually working in
here. This is the **legacy** path: pricing research was superseded by
`dashboard/backend/services/price_research.py`, and new pricing work belongs there
(see the root CLAUDE.md, "Two pricing paths"). Touch these scripts only when the
Excel workflow itself needs it.

## Data flow

`scripts/main.py` runs three sub-scripts in order, stopping on failure:

```
append_sold_orders → get_active → avg_active_price
```

- **append_sold_orders.py** — pulls orders via Trading API, enriches with Finances API fee data, dedupes by (Item ID, Sale Date), appends to the Excel "Sold Orders" sheet. Multi-item orders: order-level totals only appear on the first row.
- **get_active.py** — refreshes the Excel "Active Listings" sheet from the Trading API; estimates fees via `listing_economics`, pulls ad rates from the Marketing API, and preserves existing analytics columns across runs.
- **avg_active_price.py** — superseded by `price_research.py`. Note it does **not** apply the `comp_filter` screening the Postgres path does, so its comp pool still contains graded slabs, lots and wrong prints.
- **price_active_listings.py** — the Excel path's sold-side research (TCGdex market price → the workbook's "Recent Sold Avg" + SQLite `price_snapshots`). **Removed from the chain**: the sold side was removed everywhere else, and leaving this in kept refilling exactly what was taken out. The file remains; nothing runs it.
- **auto_boost_promotion.py** — raises promoted-listing ad rates for stale inventory (every 10 unsold days, +1%, capped); refuses to run on non-Cost-Per-Sale campaigns. **No longer part of the pipeline** — `main.py` used to end with it, and it was removed so an unattended run can never move ad spend. Run it by hand or not at all; don't re-add it to `main.py`.

## Before running anything here

`auto_boost_promotion.py` issues **live eBay writes** — real ad spend, not
trivially reversible. Load the `ebay-listing-dry-run` skill first; `--dry-run`
previews its changes. `scripts/main.py` no longer writes anything to eBay (it
reads, and updates the workbook), so it has no `--dry-run`.
