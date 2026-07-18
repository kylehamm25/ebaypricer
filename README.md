# eBay Automation

Automated eBay selling pipeline for Pokemon card listings. Fetches sold orders, refreshes active listings, computes market prices, and manages promoted listing bids.

## Motivation

Managing a high-volume Pokemon card inventory manually became increasingly time-consuming. This project automates pricing research, bookkeeping, listing management, and promoted listing optimization, allowing inventory to stay competitively priced while reducing repetitive seller tasks.

## Features

- **Sold Order Tracking** — Pulls completed orders from the Trading API, calculates eBay fees via the Finances API, deduplicates, and appends to an Excel workbook for bookkeeping.
- **Active Listing Management** — Refreshes active listings with card name enrichment (fuzzy matching), shipping profiles, promoted listing ad rates, and price analytics columns.
- **Market Price Analytics** — Searches eBay sold listings per card, computes weighted-average prices with recency bias and outlier removal, and writes Recent Sold Avg / Price vs Sold Avg / Recent Sold Count into the Active Listings sheet.
- **Active Price Comparison** — For each card, searches eBay for the top 5 best-match active listings and computes a market average, writing Active Avg (Top 5) and Active Count columns.
- **Automated Promotion Adjustment** — Adjusts promoted listing ad rates based on configurable pricing rules.
- **Listing Defaults Extension** — Chrome extension that fills eBay listing form defaults with one click, with customizable presets.

## Tech Stack

- Python
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

## Configuration

Promotion thresholds and pricing rules are configured in `scripts/check_pricing.py`, allowing different ad-rate strategies based on:

- Listing age
- Current item price
- Maximum promotion cap
- Increment percentage

## Data Storage

Excel is used as the primary bookkeeping interface (easy to open, edit, and share), while SQLite stores historical pricing snapshots and cached marketplace data, enabling incremental updates without repeatedly querying eBay.

## Reliability

- Automatic OAuth token refresh with persistent refresh-token workflow.
- Retry logic for transient API failures.
- Duplicate prevention for sold orders.
- Graceful handling of missing listing metadata.
- Logging for all pipeline stages.

## Scale

- Supports hundreds of active listings
- Tracks thousands of sold price snapshots
- Processes hundreds of completed sales
- Integrates four eBay APIs
- Executes automatically on an hourly schedule

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
├── check_pricing.py
├── get_prices.py
├── csv_report.py
├── gen_access_token.py
├── run_hourly.ps1
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
python scripts/gen_access_token.py   # OAuth consent -> refresh token saved to .env
```

Requires eBay Developer API credentials from [developer.ebay.com](https://developer.ebay.com).
