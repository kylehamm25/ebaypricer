Cards owned but not yet listed. The one hand-entered table in the app - eBay knows nothing about a box on the desk, so nothing syncs or overwrites it.

___
### Pricing
- `GET /inventory` reads shared comp snapshots and never researches - a pile can hold hundreds of cards, pricing on load would fire hundreds of Browse calls
- Pricing is a separate deliberate action through `POST /valuation/batch`, capped per batch
- What an unlisted row is worth: stated price, else cached comp average x shared condition multiplier (`services/inventory_value.py`)
- `manual_value` wins over comps, condition multiplier is not applied to it - a typed price already is that card's value

___
### Leaving the Pile
- `archived_at` records that a row left the pile, not that it is on eBay - nothing reconciles against `active_listings`
- Archived rows drop out of reads, totals, and lot unlisted columns
- Two routes to a listing: File Exchange CSV (creates listings outright) or prefill template (eBay suggests category/title/aspects, finished in Seller Hub)

___
### Related
- [[Listing CSV]]
- [[Active Listings]]
