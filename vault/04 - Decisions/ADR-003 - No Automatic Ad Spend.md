# ADR-003 - No Automatic Ad Spend

- Status: accepted
- Date: 2026-10-06

___
### Context
- `auto_boost_promotion.py` raised ad rates for stale inventory on a timer (+1% per 10 unsold days)
- The pipeline ran it unattended every hour

___
### Decision
- Ad rates are real, not-trivially-reversible spend - nothing may move them on a timer
- Scheduled round and pipeline step both removed, `services/promotion_boost.py` runs only on deliberate `POST /ebay/promotion-boost`
- Listing CSV carries no ad rate for the same reason - a rate baked into a fifty-row upload is automatic spend

___
### Alternatives
- Keep the timer with a cap - rejected, capped automatic spend is still automatic spend
- Dry-run previews on a schedule - kept only as a manual step via the `ebay-listing-dry-run` skill

___
### Related
- [[Listing CSV]]
- [[Decision Log]]
