Live eBay listings with a server-computed suggested price per row. List page and detail page show the same number.

___
### How They Stay Current
- `services/ebay_data.py` per-user OAuth sync on a scheduler and on demand (legacy Excel chain retired Oct 2026)
- Page refresh buttons run the OAuth sync for that slice (`services/stage_runner.py`); Active also forces shared research
- Research: shared `price_research.py` (once per card) or per-listing Refresh button (`refresh_card`)

___
### Rules
- Applying a price changes the price and nothing else - Best Offer thresholds are the seller's, repricing never reads or writes them
- A listing's catalog match is editable and sticks (`PUT /active/item/{id}/card`, `card_locked`) - syncs must not overwrite a hand correction
- Price history: every applied change lands in `price_change_log`, readable at `/log`
- Bulk apply has no partial state - a price either landed or it didn't
- Floor raise is preview-then-confirm (`POST /active/floor/preview` lists every row below the floor with its exact revision; `POST /active/floor/apply` moves only confirmed ids, ≤100 per call)
- Detail page tiles come from the filtered snapshot (Active Avg landed, like the list page); the table below shows the cheapest 15 raw comps, so rows can sit outside the tiles

___
### Related
- [[Pricing Model]]
- [[Sold Orders]]
- [[Inventory]]
