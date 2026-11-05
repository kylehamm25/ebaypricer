# Hand-run tools (`scripts/`)

Moved out of the root CLAUDE.md so it loads only when you are actually working in
here. The legacy Excel chain (`main.py`: `append_sold_orders → get_active →
avg_active_price`, plus `price_active_listings.py` and `run_hourly.ps1`) was
**deleted Oct 2026** with the pipeline retirement — sync runs inside the backend
now (`services/ebay_data.py` per-user OAuth sync on a scheduler, plus the
page-level refresh buttons via `services/stage_runner.py`). Don't recreate a
script here that duplicates either of those; add a backend service/endpoint
instead.

What remains:

- **auto_boost_promotion.py** — raises promoted-listing ad rates for stale inventory (every 10 unsold days, +1%, capped); refuses to run on non-Cost-Per-Sale campaigns. **Hand-run only, never on a timer**: ad rates are real, not-trivially-reversible spend. Don't re-add it to any scheduled path.
- **gen_access_token.py** — one-time OAuth consent flow, writes tokens to `.env`. Unrelated to the per-user `ebay_connections` flow; still used by `auto_boost_promotion.py`'s legacy `.env` token.
- **probe_item_sales.py** — one-shot, read-only probe of the Marketplace Insights Item Sales API (`--q`, `--limit`): validates whether genuine sold comps are usable before anyone reopens sold-side research (ADR-002). Refuses to call eBay when the connection's granted scopes lack `sell.marketplace.insights.readonly` — reconnect on Settings first, tokens never gain scopes retroactively.
- **check_card_scan.py** — read-only calibration tool for the photo scanner: `python scripts/check_card_scan.py path\to\card.jpg` prints the OCR text, detected name/number, confidence and ranked catalog candidates. It uses local OCR plus catalog art hashes and never calls eBay or writes an import. Kept beside the scanner so confidence thresholds can be checked against real photos without going through the dashboard.

## Before running anything here

`auto_boost_promotion.py` issues **live eBay writes** — real ad spend, not
trivially reversible. Load the `ebay-listing-dry-run` skill first; `--dry-run`
previews its changes.
