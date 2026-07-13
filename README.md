# eBay Price

Automated eBay selling pipeline for Pokemon card listings — fetches sold orders, refreshes active listings, computes market prices, and manages promoted listing bids.

## Capabilities

**Sold Order Tracking** — Pulls completed orders from the Trading API, calculates eBay fees via the Finances API, deduplicates, and appends to an Excel workbook for bookkeeping.

**Active Listing Management** — Refreshes current listings with card name enrichment (via fuzzy matching), shipping profile extraction, promoted listing ad rates, and price analytics columns.

**Market Price Analytics** — Searches eBay sold listings per card, computes weighted-average prices with recency bias and outlier removal, and writes Recent Sold Avg / Price vs Sold Avg / Recent Sold Count directly into the Active Listings sheet.

**Automated Promotion Bidding** — Adjusts promoted listing ad rates based on configurable pricing rules (see `check_pricing.py`).

**Listing Defaults Extension** — Chrome extension that fills eBay listing form defaults with one click, with customizable presets using popup UI.

## Pipeline

All steps run sequentially via `scripts/main.py`:

```
append_sold_orders → get_active → price_active_listings → check_pricing
```

Hourly execution is supported through `scripts/run_hourly.sh` (anacron/cron).

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
├── price_active_listings.py
├── check_pricing.py
├── get_prices.py
├── csv_report.py
├── gen_access_token.py
├── run_hourly.sh
└── run_daily.sh
ebay-defaults-extension/  Chrome extension for listing form defaults
data/                    card DB + pricing caches
db/                      SQLite (sold listings, price snapshots)
```

## Setup

```bash
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # fill in EBAY_APP_ID, EBAY_SECRET, EBAY_DEV_ID
python scripts/gen_access_token.py   # OAuth consent → refresh token saved to .env
```

Requires eBay Developer API credentials from [developer.ebay.com](https://developer.ebay.com).
