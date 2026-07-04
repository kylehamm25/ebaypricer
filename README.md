# eBay Sold Orders Exporter

Daily pipeline that fetches eBay sold orders via the Trading API, enriches them with fees from the Finances API, deduplicates, and appends them to an Excel workbook.

## Setup

### 1. Get eBay API Credentials

1. Go to [developer.ebay.com](https://developer.ebay.com) and create an account
2. Create a new app under **My Account → Application Keysets**
3. Copy your **App ID (Client ID)**, **Client Secret**, and **Dev ID**

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

For development, install the package in editable mode:

```bash
pip install -e .
```

### 3. Configure credentials

```bash
cp .env.example .env
# Fill in EBAY_APP_ID, EBAY_SECRET, EBAY_DEV_ID
```

### 4. Generate a refresh token

```bash
python scripts/gen_access_token.py
```

This opens a browser to authorize the app. Paste the redirected URL back into the terminal — the refresh token is saved to `.env` automatically.

### 5. Run it

```bash
python scripts/append_sold_orders.py
```

## Usage

### Append recent sold orders to an existing workbook

```bash
python scripts/append_sold_orders.py
```

Options:

| Flag | Description |
|---|---|
| `--output` | Output xlsx path (default: `H:\My Drive\ebay\ebay_sold_orders.xlsx`) |
| `--days` | Fetch last N days (default `0` = use hardcoded cutoff `2026-06-29`) |

### Daily automation (Linux / WSL)

A bash wrapper is included for anacron/cron:

```bash
# Install anacron (Ubuntu/Debian)
sudo apt install anacron

# Copy the wrapper
sudo cp scripts/run_daily.sh /etc/cron.daily/ebay_sold
sudo chmod 755 /etc/cron.daily/ebay_sold
```

Anacron runs all daily jobs shortly after boot, even on machines that aren't on 24/7.

## Project Layout

```
├── src/ebaypricer/          # reusable Python package
│   ├── auth.py              # OAuth token management (Trading + Browse APIs)
│   ├── trading_api.py       # eBay Trading API (sold orders, active listings)
│   ├── browse_api.py        # eBay Browse API (item search, price snapshots)
│   ├── finances.py          # eBay Finances API (fee fetching)
│   ├── cards.py             # Pokemon card database + fuzzy matching
│   ├── excel.py             # shared Excel styling helpers
│   └── paths.py             # centralized file paths
├── scripts/                 # executable entry points
│   ├── main.py              # orchestrator (runs all daily pipelines)
│   ├── append_sold_orders.py
│   ├── get_active.py
│   ├── price_active_listings.py
│   ├── get_prices.py
│   ├── csv_report.py
│   ├── gen_access_token.py
│   ├── check_pricing.py
│   └── run_daily.sh
├── data/                    # JSON cache files (Pokemon card DB, pricing)
├── db/                      # SQLite database (sold listings + price snapshots)
├── tests/                   # test stubs
├── .env.example
├── pyproject.toml
└── requirements.txt
```
