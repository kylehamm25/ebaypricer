# ADR-002 - No Sold-Side Research

- Status: accepted
- Date: 2026-10-06

___
### Context
- Pricing needs real sold comps to anchor against
- Browse API has a `soldDate` filter that looks like it returns sold listings

___
### Decision
- No sold-side research at all - the Browse API silently ignores the `soldDate` filter and returns ordinary active listings, so anything labeled sold from Browse is wrong
- TCGdex market-price lookup was removed too - one asking-price point read as sold data on every screen it reached
- `price_accuracy` is measured against the comp average alone
- Real sold comps need eBay's Marketplace Insights API (restricted access, not on this app's scopes)

___
### Alternatives
- Browse sold search - rejected, returns active listings mislabeled
- Market-price lookup labeled as sold - rejected, an asking price is not a sale
- Marketplace Insights API - blocked until access is granted

___
### Consequences
- Do not reintroduce a Browse sold search or a sold number derived from a market-price lookup
- [[Sold Orders]] (your real sales) are untouched by this - they are actual order data, not research

___
### Related
- [[Pricing Model]]
- [[Browse API Gotchas]]
- [[Decision Log]]
