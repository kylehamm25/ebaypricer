Buying lots grouped by the SKU already stamped on listings and orders (`L0030`, `L0041`, ...). Only user-entered fields are stored: title, cost, purchase date, source, notes.

___
### Rules
- `PULL`, `NONTCG`, and rows with no SKU are not purchased lots - excluded, but only after per-line allocation, or a mixed order's whole net lands on the one real lot
- Units sold, net proceeds, live items, listed value are aggregated on read - a lot appears as soon as its SKU exists in the data
- Unlisted stock (`inventory` rows with the lot's SKU) rolls up as `unlisted_items` / `unlisted_value`, counted apart from `active_items`
- `projected_profit` (sold net + listed + unlisted value - cost) is optimistic on two counts: no fees off the unsold half, and the unlisted part is asking prices, not agreed sales

___
### Related
- [[Sold Orders]]
- [[Inventory]]
