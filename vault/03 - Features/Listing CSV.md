Where an inventory row leaves the app. Turns selected rows into one of eBay's two bulk-upload files. Pure function of rows + cached snapshots, never researches.

___
### Modes
- **draft** (default) - draft-listing template, rows land in ebay.com/sh/lst/drafts, no business-policy columns, no Settings prerequisite
- **add** - File Exchange template, creates listings outright, needs all four Settings fields (location + shipping/payment/return policy names)

___
### Rules
- Both modes need a photo - eBay rejects photoless listings, a row without one is warned not skipped
- Unpriced rows are skipped, sealed/bulk rows are skipped (no `card_query`, would land in the wrong category)
- `*StartPrice` is the condition-adjusted comp average clamped by fee/postage floor and seller `min_price`, not the suggested-price model (an unlisted card has no current price, days sat, rank, or watchers)
- No ad rate baked in, no Best Offer, no graded cards (comp pool screens slabs out)
- Title capped at 80 chars, trimmed from the least identifying end so the grade abbreviation survives

___
### Related
- [[Inventory]]
