Your real sales. Untouched by pricing research, which only reads active listings.

___
### How They Arrive
- Trading API pulls orders, Finances API adds fee data, dedupe by (Item ID, Sale Date)
- Multi-item orders: order-level totals appear on the first row only
- Per-user OAuth sync writes `sold_orders` (legacy Excel path retired Oct 2026)

___
### Money Trap
- eBay puts order-level money on one row of a multi-item order
- `SUM(order_earnings)` grouped by SKU credits a whole mixed order to one lot and zeroes the others
- Per-SKU aggregates must split each order's net across its lines by share of item value instead

___
### Related
- [[Active Listings]]
- [[Lots]]
