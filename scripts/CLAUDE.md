# Legacy Excel pipeline (`scripts/`)

Moved out of the root CLAUDE.md so it loads only when you are actually working in
here. This is the **legacy** path: pricing research was superseded by
`dashboard/backend/services/price_research.py`, and new pricing work belongs there
(see the root CLAUDE.md, "Two pricing paths"). Touch these scripts only when the
Excel workflow itself needs it.

## Data flow

`scripts/main.py` runs five sub-scripts in order, stopping on failure except the
last (best-effort):

```
append_sold_orders → get_active → price_active_listings → avg_active_price → auto_boost_promotion
```

- **append_sold_orders.py** — pulls orders via Trading API, enriches with Finances API fee data, dedupes by (Item ID, Sale Date), appends to the Excel "Sold Orders" sheet. Multi-item orders: order-level totals only appear on the first row.
- **get_active.py** — refreshes the Excel "Active Listings" sheet from the Trading API; estimates fees via `listing_economics`, pulls ad rates from the Marketing API, and preserves existing analytics columns across runs.
- **price_active_listings.py** / **avg_active_price.py** — superseded by `price_research.py`. Note these do **not** apply the `comp_filter` screening the Postgres path does, so their comp pools still contain graded slabs, lots and wrong prints.
- **auto_boost_promotion.py** — raises promoted-listing ad rates for stale inventory (every 10 unsold days, +1%, capped); refuses to run on non-Cost-Per-Sale campaigns.

## Before running anything here

`scripts/main.py` and `auto_boost_promotion.py` issue **live eBay writes** — real
price revisions and real ad spend. Load the `ebay-listing-dry-run` skill first;
`--dry-run` previews promotion changes only.
