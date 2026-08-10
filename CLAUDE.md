# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An automated eBay selling pipeline for a Pokemon card business, plus a dashboard to view the data. Two halves that share a database but run independently:

1. **Pipeline** (`src/ebaypricer/` + `scripts/`) — Python scripts that talk to eBay's Trading/Browse/Marketing/Finances APIs, do pricing research, and read/write an Excel workbook (`H:\My Drive\ebay\ebay_sold_orders.xlsx`, path in `EBAY_EXCEL_PATH`) as the bookkeeping source of truth. Runs hourly via Windows Task Scheduler (`scripts/run_hourly.ps1`).
2. **Dashboard** (`dashboard/backend` FastAPI + `dashboard/frontend` React/Vite) — reads from Postgres/Supabase, displaying sold orders, active listings, pricing, and promotions. On startup it syncs the Excel workbook into Postgres (`services/excel_sync.py`).

The project is mid-migration from a single-user local SQLite tool to a multi-user Supabase-backed SaaS. **Read `docs/SOFTWARE_PLAN.md` before touching schema, auth, or the migration path** — it documents the current vs. target architecture, the full Postgres schema, and the phase plan. Treat it as living design doc, not historical record; update it when a phase completes or the plan changes.

A third piece, `ebay-defaults-extension/`, is a standalone Chrome extension (vanilla JS, no build step) for filling eBay listing form defaults — unrelated to the Python/dashboard code.

## Commands

### Pipeline (Python, from repo root)
```bash
pip install -r requirements.txt
pip install -e .                        # installs src/ebaypricer as editable package
python scripts/main.py                  # full pipeline, sequential, logs to logs/main.log
python scripts/main.py --dry-run        # preview promotion changes only
python scripts/gen_access_token.py      # one-time OAuth consent flow -> writes tokens to .env
python scripts/price_active_listings.py --force   # bypass daily SQLite cache
```
No test suite exists in this repo currently.

### Dashboard backend (FastAPI, from repo root)
```bash
pip install -r requirements-dashboard.txt
python -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### Dashboard frontend (from `dashboard/frontend/`)
```bash
npm install
npm run dev       # Vite dev server on :5173
npm run build     # tsc -b && vite build -> dist/
npm run lint      # oxlint
npm run preview
```

### Full stack shortcuts
- `start-dashboard.bat` — starts backend (:8000) and frontend dev server (:5173) in separate windows, dev mode.
- `start-prod.bat` — builds the frontend if needed, installs deps, serves everything from FastAPI on :8000 (single-host mode).
- `Dockerfile` — multi-stage build (Node for frontend, Python 3.13-slim for backend); frontend `VITE_*` build args are baked in at image build time, not runtime.

## Architecture

### Pipeline data flow
`scripts/main.py` runs five sub-scripts in order, stopping on failure except the last (best-effort):
```
append_sold_orders → get_active → price_active_listings → avg_active_price → auto_boost_promotion
```
- **append_sold_orders.py** — pulls orders via Trading API, enriches with Finances API fee data, dedupes by (Item ID, Sale Date), appends to the Excel "Sold Orders" sheet. Multi-item orders: order-level totals only appear on the first row.
- **get_active.py** — refreshes the Excel "Active Listings" sheet from the Trading API; estimates fees via tiered net-percentage multipliers, pulls ad rates from the Marketing API, and preserves existing analytics columns across runs.
- **price_active_listings.py** — for each unique card, searches eBay sold listings via the Browse API, computes an outlier-filtered weighted average (recent sales weighted 2x), caches per-day results in SQLite `price_snapshots`.
- **avg_active_price.py** — searches active listings, averages the 5 cheapest, computes `Price Accuracy` against the midpoint of sold/active benchmarks, caches in `active_snapshots`.
- **auto_boost_promotion.py** — raises promoted-listing ad rates for stale inventory (every 10 unsold days, +1%, capped); refuses to run on non-Cost-Per-Sale campaigns.

Shared library in `src/ebaypricer/`: `auth.py` (OAuth token refresh, persisted to `.env`), `trading_api.py`, `browse_api.py`, `marketing_api.py`, `finances.py`, `cards.py` (Pokemon card DB + fuzzy matching, caches in `data/`), `excel.py` (workbook styling), `paths.py` (all file paths — `PROJECT_ROOT`, `DB_PATH`, cache files; import from here rather than hardcoding paths).

Local SQLite lives at `db/pokemon_prices.db`. Some tables are shared marketplace data (`price_snapshots`, `active_snapshots`, `sold_listings`), rebuilt/appended incrementally; others mirror the workbook and get dropped/recreated each sync — see `docs/SOFTWARE_PLAN.md` §3 for the full schema and which tables are "shared" vs "user-owned" in the Supabase target.

### Dashboard backend
FastAPI app in `dashboard/backend/main.py`. On startup: syncs the Excel workbook into Postgres staging tables (`services/excel_sync.py`) and, if any eBay connections exist, starts a background scheduler (`services/ebay_data.py`) for per-user syncs. Serves the built frontend (`dashboard/frontend/dist`) directly when present, with SPA fallback routing — so in single-host/prod deployment there's one process on :8000.

- `database.py` — psycopg3 connection pool (`get_db()`), defaults to read-only transactions.
- `config.py` — all env vars, read through `_env()` which strips surrounding quotes (needed because Docker `--env-file` keeps them). Env vars are organized by migration phase — check `.env.example` for the phase each one belongs to before adding new config.
- `auth.py` — Supabase JWT verification (`get_current_user_id`), tries ES256-via-JWKS first, falls back to legacy HS256-via-shared-secret. When `AUTH_REQUIRED` is unset, falls back to `DEFAULT_USER_ID` for local single-user dev.
- `routers/` — one file per resource (`dashboard`, `sold`, `active`, `pricing`, `pipeline`, `promotion`, `ebay`); `pipeline.py` can trigger `scripts/main.py` as a subprocess and reports status/logs.
- `services/ebay_client.py`, `ebay_oauth.py`, `ebay_data.py` — per-user eBay OAuth (PKCE) and sync scheduler, the Phase 5/6 multi-user work described in the software plan. Refresh tokens are Fernet-encrypted at rest (`EBAY_TOKEN_ENCRYPTION_KEY`).
- SQL is Postgres-flavored (the migration off SQLite is done at the DB layer); don't reintroduce SQLite-specific syntax (`?` params, `CAST(x AS REAL)`, `strftime`) in new queries — see the mapping rules in `docs/SOFTWARE_PLAN.md` §6.3 if porting old SQL.

### Dashboard frontend
React 19 + TypeScript + Vite, Tailwind v4, TanStack Query, react-router-dom v7, Recharts, Supabase JS client for auth.
- `lib/api.ts` — API client, base URL from `VITE_API_BASE` (defaults to local backend).
- `lib/auth.tsx` / `auth-context.ts` — Supabase session provider; `App.tsx` gates all routes except `/login` behind a `Protected` wrapper.
- `pages/` — one file per route (Dashboard, SoldOrders, ActiveListings, ListingDetail, Pricing, Promotions, Settings, Login).
- `components/shared/` — `DataTable`, `KpiCard`, `Skeleton` reused across pages.
- Linting is oxlint (`.oxlintrc.json`), not ESLint.

## Working across the pipeline/dashboard boundary

Pipeline scripts write to Excel + local SQLite; the dashboard reads Postgres and re-syncs from Excel on each startup/trigger. If you change a column name or add a field in the Excel sheets (`get_active.py`, `append_sold_orders.py`), you must also update the corresponding column-mapping dict in `dashboard/backend/services/excel_sync.py` (`_SOLD_COLUMNS`, `_ACTIVE_COLUMNS`) or the new field silently won't reach the dashboard.
