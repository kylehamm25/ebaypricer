# eBay Automation

Automated eBay selling pipeline for Pokemon card listings. Fetches sold orders, refreshes active listings, computes market prices, and manages promoted listing bids.

## Motivation

Managing a high-volume Pokemon card inventory manually became increasingly time-consuming. This project automates pricing research, bookkeeping, listing management, and promoted listing optimization, allowing inventory to stay competitively priced while reducing repetitive seller tasks.

## Features

- **Sold Order Tracking** - Pulls completed orders from the Trading API, calculates eBay fees via the Finances API, deduplicates, and appends to an Excel workbook for bookkeeping.
- **Active Listing Management** - Refreshes active listings with card name enrichment (fuzzy matching), shipping profiles, promoted listing ad rates, and price analytics columns.
- **Market Price Analytics** - Searches eBay sold listings per card, computes weighted-average prices with recency bias and outlier removal, and writes Recent Sold Avg / Price vs Sold Avg / Recent Sold Count into the Active Listings sheet.
- **Active Price Comparison** - For each card, searches eBay for the top 5 best-match active listings and computes a market average, writing Active Avg (Top 5) and Active Count columns.
- **Automated Promotion Adjustment** - Adjusts promoted listing ad rates based on configurable pricing rules.
- **Listing Defaults Extension** - Chrome extension that fills eBay listing form defaults with one click, with customizable presets.

## Scale

- Supports hundreds of active listings
- Tracks thousands of sold price snapshots
- Processes hundreds of completed sales
- Integrates four eBay APIs
- Executes automatically on an hourly schedule

## Tech Stack

- Python 3.12
- SQLite
- openpyxl
- eBay Trading API
- eBay Browse API
- eBay Marketing API
- eBay Finances API
- OAuth 2.0
- Chrome Extension (JavaScript)
- PowerShell / Bash

## Pipeline

All steps run sequentially via `scripts/main.py`:

```
append_sold_orders → get_active → price_active_listings → avg_active_price → auto_boost_promotion
```

Hourly execution is supported through `scripts/run_hourly.ps1` (Windows) or `scripts/run_hourly.sh` (anacron/cron).

## Performance

- Incremental updates avoid reprocessing historical orders.
- SQLite caches sold-listing snapshots to reduce API usage.
- Duplicate sold listings are automatically filtered across daily runs.
- Weighted averages prioritize recent market activity.
- Outlier filtering removes anomalous sale prices before averaging.
- Automatic OAuth token refresh minimizes authentication interruptions.

## Data Storage

- Excel is used as the primary bookkeeping interface for readability
- SQLite stores historical pricing snapshots and cached marketplace data, enabling incremental updates without repeatedly querying eBay.

## Reliability

- Automatic OAuth token refresh with persistent refresh-token workflow.
- Retry logic for transient API failures.
- Duplicate prevention for sold orders.
- Graceful handling of missing listing metadata.
- Logging for all pipeline stages.

## Scripts Reference

### `main.py` 

The entry point for the full automation pipeline. Runs five sub-scripts sequentially, stopping on failure (except `auto_boost_promotion` which is best-effort). Supports `--dry-run` to preview promotion changes without applying them. All output is logged to `logs/main.log` with timestamps.

```
python scripts/main.py
python scripts/main.py --dry-run
```

**Pipeline order:**
1. `append_sold_orders.py` - import new sales
2. `get_active.py` - refresh active listings
3. `price_active_listings.py` - sold-price research
4. `avg_active_price.py` - active-market comparison
5. `auto_boost_promotion.py` - adjust ad rates

### `append_sold_orders.py`

Pulls completed orders via the Trading API within a date range, enriches each sale with eBay fee data from the Finances API, deduplicates against existing rows, and appends new orders to the Sold Orders sheet in the Excel workbook.

**Key behaviors:**
- Default cutoff is `2026-06-30`; override with `--days N` to fetch the last N days.
- Deduplicates by (Item ID, Sale Date) to prevent re-importing.
- Strips deprecated columns automatically when opening existing workbooks.
- For multi-item orders, order-level values (Shipping, Total, Fees, Earnings) appear only on the first/highest-priced item row; continuation rows leave those fields blank.
- Enriches each row with card metadata via fuzzy matching against the Pokemon card database.

```
python scripts/append_sold_orders.py
python scripts/append_sold_orders.py --days 7
python scripts/append_sold_orders.py --output "\path\to\sheet.xlsx"
```

### `get_active.py`

Fetches all current active listings from the Trading API, enriches them with card names, shipping cost estimates, and promoted listing ad rates from the Marketing API, then rewrites the Active Listings sheet in Excel.

**Key behaviors:**
- Maps shipping profile names to estimated costs (e.g., "Free Shipping" → $0.00, "Ebay Standard Envelope" → $0.78).
- Estimates fees using tiered multipliers: 65% net for items ≤ $2, 70% for ≤ $5, 73% otherwise.
- Pulls ad-rate percentages for each listing
- Restores existing price analytics columns (Recent Sold Avg, Price vs Sold Avg, etc.) so they aren't lost on refresh.
- Preserves cached card names across runs to maintain consistency.

```
python scripts/get_active.py
python scripts/get_active.py --output "\path\to\sheet.xlsx"
```

### `price_active_listings.py`

For each unique card in the Active Listings sheet, searches eBay completed/sold listings via the Browse API, computes a weighted-average sold price, and writes analytics columns back to the sheet.

**Key behaviors:**
- Searches up to 10 sold matches per card, filtered to the last 30 days.
- Removes statistical outliers beyond 1.5 sigma before averaging.
- Weighted average: recent sales (≤ 14 days) weighted 2x, older sales 1x.
- Caches results in SQLite (`price_snapshots` table) — re-runs on the same day are no-ops unless `--force` is used.
- Writes columns: `Recent Sold Avg`, `Price vs Sold Avg`, `Recent Sold Count`, `Last Checked`.
- Each sold listing is also saved to the `sold_listings` table for debugging.

```
python scripts/price_active_listings.py
python scripts/price_active_listings.py --force
python scripts/price_active_listings.py --max-listings 100
python scripts/price_active_listings.py --db "C:\path\to\custom.db"
```

### `avg_active_price.py`

For each unique card, searches currently active eBay listings via the Browse API, takes the 5 "Best Match" listing prices, averages them, and writes `Active Avg` to the sheet.

**Key behaviors:**
- Targets highest placing listings
- Caches results in SQLite (`active_snapshots` table) to avoid redundant API calls.
- Prints a summary table with per-card averages and a grand average across all cards.
- Respects `--force` to bypass daily cache.
- Rate-limited with a 0.5s sleep between calls.

```
python scripts/avg_active_price.py
python scripts/avg_active_price.py --force
python scripts/avg_active_price.py --max-listings 100
```

### `auto_boost_promotion.py`

Automatically increases promoted listing ad rates for stale inventory. Every 10 days an item has been listed without selling, its ad rate is bumped by 1% (computed via `marketing_api.compute_target_bid`), up to a configurable cap.

**Key behaviors:**
- Default cap is 5.0%; items over $50 cap at 3.0%.
- Targets the first RUNNING Cost-Per-Sale campaign; specify a different campaign with `--campaign-name` or `--campaign-id`.
- Validates the campaign funding model — refuses to run on Cost-Per-Click campaigns.
- Processes updates in batches of 500 via the Marketing API's `bulk_update_bids` endpoint.
- `--dry-run` prints what would be changed without applying.

```
python scripts/auto_boost_promotion.py
python scripts/auto_boost_promotion.py --dry-run
python scripts/auto_boost_promotion.py --campaign-name "Example Campaign" --max-bid 10.0
python scripts/auto_boost_promotion.py --min-days 5 --debug
```

### `gen_access_token.py`

One-time setup script that walks through the eBay OAuth 2.0 authorization code flow. Opens the eBay consent page in a browser, captures the redirect URL, exchanges the authorization code for access and refresh tokens, then saves them to `.env`.

**Key behaviors:**
- Requests scopes: `sell.inventory.readonly`, `sell.fulfillment.readonly`, `sell.marketing`.
- Validates that `sell.marketing` was granted (required for promotion features).
- Persists both ACCESS_TOKEN and REFRESH_TOKEN to the `.env` file.
- At runtime, `auth.py` automatically refreshes the access token using the stored refresh token.

```
python scripts/gen_access_token.py
```

### `run_hourly.ps1`

PowerShell script designed for Windows Task Scheduler. Activates the project's virtual environment, runs `main.py`, and appends stdout/stderr to `%USERPROFILE%\ebay_exports\run_hourly.log` with timestamps.

```powershell
.\scripts\run_hourly.ps1
```

## Project Layout

```
src/ebaypricer/          core library
├── auth.py              OAuth 2.0 token management
├── trading_api.py       eBay Trading API (orders, active listings)
├── browse_api.py        eBay Browse API (sold search, snapshots)
├── finances.py          eBay Finances API (fee breakdowns)
├── cards.py             Pokemon card database + fuzzy matching
├── excel.py             shared styling helpers
├── marketing_api.py     promoted listings campaign/ads API
└── paths.py             centralized file paths
scripts/                 entry points
├── main.py              pipeline orchestrator
├── append_sold_orders.py
├── get_active.py
├── avg_active_price.py
├── price_active_listings.py
├── auto_boost_promotion.py
├── gen_access_token.py
└── run_hourly.ps1
ebay-defaults-extension/  Chrome extension for listing form defaults
data/                    card DB + pricing caches
db/                      SQLite (sold listings, price snapshots)
```

## Setup

```bash
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # fill in EBAY_APP_ID, EBAY_SECRET, EBAY_DEV_ID
python scripts/gen_access_token.py   # OAuth consent -> refresh token saved to .env
```

Requires eBay Developer API credentials from [developer.ebay.com](https://developer.ebay.com).
