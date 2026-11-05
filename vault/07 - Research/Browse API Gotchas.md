Browse matches on words, not card identity. Its results are not usable as-is.

___
### soldDate Is Ignored
- Browse silently ignores the `soldDate` filter and returns ordinary active listings
- Anything labeled sold from Browse is wrong - this is why [[ADR-002 - No Sold-Side Research]] exists

___
### Catalog Identity vs Search String
- `card_query` keys the snapshot tables, it is not a search string
- SVP promos are catalogued `SVP13` but titled `SVP 013` - searching the catalogued form returned zero results
- `browse_api` runs every query through `searchable_card_query` first
- Never change `_fmt_card` / `card_query` to fix a search problem

___
### Pool Contamination
- A comp pool arrives mixed with graded slabs, multi-card lots, print-error one-offs, foreign/Japanese prints, wrong prints, stamped promos (Surprise Box stamps trade ~3x the plain print - caught Oct 2026 doubling a card's average)
- `comp_filter.py` screens them out before any aggregate, drops recorded in `pool_quality`
- Add new rules in `comp_filter.py`, not in aggregation code

___
### Related
- [[Pricing Model]]
- [[eBay APIs]]
