Four eBay APIs plus a card catalog. Per-user OAuth with Fernet-encrypted refresh tokens.

___
### APIs
- **Trading API** - orders, active listings, price revisions (`trading_api.py`)
- **Browse API** - active-listing search for comp aggregation (`browse_api.py`)
- **Marketing API** - promoted-listing ad rates, read only (`marketing_api.py`)
- **Finances API** - per-order fees and earnings (`finances.py`)
- **Card catalog** - `cards.py`, fuzzy title matching, caches in `data/`
- Catalog source is the pokemon-tcg-data GitHub repo, plus a TCGdex backfill for the promo sets it lacks (MEP promos, SVP166+, SVP500 - merged in `_build_cache`, details cached in `data/tcgdex_promo_cards.json`)

___
### Gotchas
- Browse silently ignores the `soldDate` filter, returns ordinary active listings - see [[Browse API Gotchas]]
- `card_query` is a catalog identity, not a search string - `browse_api` runs it through `searchable_card_query` first (SVP promos are catalogued `SVP13` but titled `SVP 013`)
- Shipping: prefer eBay's `ShippingServiceCost` when returned, else static per-profile estimate (`resolve_shipping_charge`)
- Rate limits, retry, and caching behavior live in the `ebay-api-rate-limits` skill - read it before adding any research loop

___
### Related
- [[System Architecture]]
- [[Pricing Model]]
