Suggested price is computed server-side by a single pure function. The frontend only displays it, never computes it.

___
### Current Path
- `dashboard/backend/services/price_research.py` - shared research, runs once per unique card across all users, writes shared snapshots + every user's derived columns
- `services/suggested_price.py` - the single canonical pricing model
- Legacy Excel path (`scripts/price_active_listings.py` + `avg_active_price.py`) deleted Oct 2026 with the pipeline retirement

___
### Rules
- `suggested_price.py` is pure: no DB, no network, no clock, callers pass clock-derived inputs in
- Never compute a price in the frontend - a client-side version once produced different numbers on list vs detail page, so it was deleted
- Tuning constants live at the top of `suggested_price.py`, prose copy lives in the `ebay-pricing-rules` skill
- Reprice cooldown: no new suggestion for 5 days after an applied change (`price_change_log` drives it)
- Stale hold: unsold 30+ days, a suggestion may hold or cut, never increase (profitability floor still applies)
- `price_accuracy` is measured against the comp average alone

___
### Comp Pool
- Browse matches on words, not card identity, so results arrive contaminated
- `src/ebaypricer/comp_filter.py` screens out graded slabs, multi-card lots, print-error one-offs, foreign prints, wrong prints, stamped promos
- What got dropped is recorded in `active_price_snapshots.pool_quality`
- New contamination rules go in `comp_filter.py`, not in aggregation code

___
### Related
- [[System Architecture]]
- [[Active Listings]]
- [[Browse API Gotchas]]
- [[ADR-002 - No Sold-Side Research]]
