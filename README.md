# eBay Automation

Automated eBay selling pipeline for Pokemon cards, plus a dashboard to view the data. Two halves that share a database but run independently:

1. **Pipeline** (`src/ebaypricer/` + `scripts/`) — talks to eBay's Trading/Browse/Marketing/Finances APIs, refreshes sold orders and active listings, and keeps an Excel workbook as the bookkeeping source of truth. Runs hourly via Windows Task Scheduler.
2. **Dashboard** (`dashboard/backend` FastAPI + `dashboard/frontend` React/Vite) — sold orders, active listings, inventory, lots, and pricing, backed by Postgres/Supabase. Syncs the Excel workbook on startup.

A third piece, `ebay-defaults-extension/`, is a standalone Chrome extension for filling eBay listing form defaults.

## Pipeline

```bash
pip install -e .              # required: installs src/ebaypricer
python scripts/main.py        # full run: append_sold_orders → get_active → avg_active_price
```

See `scripts/CLAUDE.md` for the per-script data flow.

## Dashboard

```bash
python -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Or use the shortcuts: `start-dashboard.bat` (dev, backend :8000 + frontend :5173) and `start-prod.bat` (single-host prod on :8000). Database migrations in `db/migrations/` are applied by hand in the Supabase SQL editor, in order.

## Setup

```bash
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # fill in credentials, see .env.example
python scripts/gen_access_token.py   # one-time eBay OAuth consent flow
```

Requires eBay Developer API credentials from [developer.ebay.com](https://developer.ebay.com).

## Docs

- `CLAUDE.md` — architecture, pricing model, and conventions
- `docs/SOFTWARE_PLAN.md` — Postgres schema and migration plan
- `dashboard/frontend/CLAUDE.md` — frontend route map and rules
