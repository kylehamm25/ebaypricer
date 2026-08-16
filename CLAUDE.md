# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An automated eBay selling pipeline for a Pokemon card business, plus a dashboard to view the data. Two halves that share a database but run independently:

1. **Pipeline** (`src/ebaypricer/` + `scripts/`) — Python scripts that talk to eBay's Trading/Browse/Marketing/Finances APIs, do pricing research, and read/write an Excel workbook (`H:\My Drive\ebay\ebay_sold_orders.xlsx`, path in `EBAY_EXCEL_PATH`) as the bookkeeping source of truth. Runs hourly via Windows Task Scheduler (`scripts/run_hourly.ps1`).
2. **Dashboard** (`dashboard/backend` FastAPI + `dashboard/frontend` React/Vite) — reads from Postgres/Supabase, displaying sold orders, active listings, and pricing. On startup it syncs the Excel workbook into Postgres (`services/excel_sync.py`).

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

### Database migrations
`db/migrations/NNNN_*.sql` are numbered, idempotent (`create ... if not exists`), and **applied by hand** — paste into the Supabase SQL editor and run in order. There is no migration runner. Code that depends on a new table should degrade rather than crash if the migration hasn't been run yet (see `price_research.recent_price_changes`, which logs and returns empty when `price_change_log` is missing).

## Architecture

### Two pricing paths (important)

Pricing research exists **twice**, and new work belongs in the second one:

- **Legacy (Excel):** `scripts/price_active_listings.py` + `scripts/avg_active_price.py`, driven by `scripts/main.py`, using the Excel workbook and local SQLite as the inter-step data channel.
- **Current (Postgres):** `dashboard/backend/services/price_research.py` — shared, server-side, runs once per unique card **across all users** and writes the shared snapshot tables plus every user's derived `active_listings` columns. It supersedes the two scripts above.

Both still exist because the legacy path serves the single-user Excel workflow while connected users go through `services/ebay_data.py`. When changing pricing logic, change `price_research.py`; only touch the scripts if the Excel workflow specifically needs it. Shared numeric helpers live in `src/ebaypricer/listing_economics.py` (tiered fee/net estimation, `resolve_shipping_charge`) precisely so both paths agree. `resolve_shipping_charge` prefers eBay's own `ShippingServiceCost` when the Trading API returns one, falling back to the static per-profile estimate (`shipping_charge_for_profile`) for Calculated-shipping listings that don't have package weight/dimensions set — both `get_active.py` and `ebay_data.py` call it the same way.

**eBay has no sold-comps API here.** The Browse API silently ignores the `soldDate` filter and returns ordinary active listings, so anything labeled "sold" from Browse is wrong. Sold-side research uses TCGdex/TCGPlayer market price via `ebaypricer.cards.lookup_market_price` (a single-point sample, `sample_size=1`), not eBay. Real sold comps would need eBay's Marketplace Insights API, which is restricted-access and not on this app's scopes. Don't "fix" this by reintroducing a Browse sold search. Active-listing search via Browse *is* real and is used as-is.

### Suggested price model
`dashboard/backend/services/suggested_price.py` is the single canonical pricing model. It is **pure** — no DB, no network, no clock — and returns a `Suggestion` carrying the price, a status, and every intermediate value, persisted to `active_listings.suggested_price_basis` so the UI can explain itself. The shape is:

```
anchors -> staleness/rank blend -> condition multiplier -> shipping adjustment
-> watcher pull -> guardrails -> rounding
```

Keep it pure: callers pass in clock-derived inputs (e.g. `days_since_price_change`) rather than letting the module read the time. This replaced a client-side `computeRecommendedPrice` that produced different numbers on the list page vs. the detail page — **don't reintroduce pricing math in the frontend.** The tuning constants at the top of the file carry the reasoning for their values in comments; read them before adjusting.

Notable inputs beyond the comp anchors: shipping adjustment repositions the target on total landed price (item + shipping) using `comp_avg_shipping` (mean shipping cost among today's comp pool, migration 0007) vs. what we charge; watcher pull dampens the move for listings with existing demand, saturating at `WATCHER_SATURATION`; `excluded_title_keyword()` declines to suggest at all for print-defect/novelty titles (holo bleed, swirl, miscut, error) since the normal comp pool says nothing about their value. `price_change_log` (migration 0005) records only price changes eBay actually accepted, and drives the reprice cooldown (`REPRICE_COOLDOWN_DAYS` = 5, status `"cooldown"`) so a listing isn't re-proposed the same edit before the last one had time to work.

### Background jobs, locks, and status
Every long-running backend job follows one pattern: a process-local `threading.Lock` for fast rejection, a **Postgres advisory lock** for cross-process exclusion, and start/finish rows in the `job_runs` table so `/pipeline/status` and the per-page refresh buttons can report progress. Advisory-lock keys must be unique per job — currently `727001` (`pipeline_runner`), `727002` (`price_research`), `727003`/`727004` (`stage_runner` sold/active). Pick a new key for a new job.

`price_research.reconcile_stale_job_runs()` runs at startup to mark rows orphaned by a crash; this assumes single-instance deployment.

Job entry points:
- `services/pipeline_runner.py` — runs the whole legacy `scripts/main.py`, then ingests Excel + SQLite into Postgres.
- `services/stage_runner.py` — page-level refresh of just one slice (`sold_refresh`, `active_refresh`), so a page can update without a full pipeline run.
- `services/price_research.py` — `run_shared_price_research()` (whole catalog, has a 45-minute wall-clock budget), `refresh_card()` (one card, bypasses the batch lock for the per-listing Refresh button), `recompute_suggestions()` (zero eBay calls; recomputes from existing snapshots).
- `services/ebay_data.py` — per-user OAuth sync, replaces the Excel workbook for connected users; runs on a background scheduler and on demand.
- `services/promotion_boost.py` — per-user ad-rate boosting using each user's own token.

### Pipeline data flow (legacy)
`scripts/main.py` runs five sub-scripts in order, stopping on failure except the last (best-effort):
```
append_sold_orders → get_active → price_active_listings → avg_active_price → auto_boost_promotion
```
- **append_sold_orders.py** — pulls orders via Trading API, enriches with Finances API fee data, dedupes by (Item ID, Sale Date), appends to the Excel "Sold Orders" sheet. Multi-item orders: order-level totals only appear on the first row.
- **get_active.py** — refreshes the Excel "Active Listings" sheet from the Trading API; estimates fees via `listing_economics`, pulls ad rates from the Marketing API, and preserves existing analytics columns across runs.
- **price_active_listings.py** / **avg_active_price.py** — superseded by `price_research.py`; see above.
- **auto_boost_promotion.py** — raises promoted-listing ad rates for stale inventory (every 10 unsold days, +1%, capped); refuses to run on non-Cost-Per-Sale campaigns.

Shared library in `src/ebaypricer/`: `auth.py` (OAuth token refresh, persisted to `.env`), `trading_api.py`, `browse_api.py`, `marketing_api.py`, `finances.py`, `cards.py` (Pokemon card DB, fuzzy matching, TCGdex market price; caches in `data/`), `listing_economics.py`, `excel.py` (workbook styling), `paths.py` (all file paths — `PROJECT_ROOT`, `DB_PATH`, cache files; import from here rather than hardcoding paths).

Local SQLite lives at `db/pokemon_prices.db`. Some tables are shared marketplace data (`price_snapshots`, `active_snapshots`, `sold_listings`), rebuilt/appended incrementally; others mirror the workbook and get dropped/recreated each sync — see `docs/SOFTWARE_PLAN.md` §3 for the full schema and which tables are "shared" vs "user-owned" in the Supabase target.

### Dashboard backend
FastAPI app in `dashboard/backend/main.py`. On startup: reconciles orphaned `job_runs`, starts the per-user sync scheduler if any eBay connections exist, then syncs the Excel workbook into Postgres. Serves the built frontend (`dashboard/frontend/dist`) directly when present, with SPA fallback routing — so in single-host/prod deployment there's one process on :8000.

- `database.py` — psycopg3 connection pool (`get_db()`), defaults to read-only transactions. The pool is small (5); never take a second connection while holding one (pass data down instead — see `update_active_listing_derived_columns`).
- `config.py` — all env vars, read through `_env()` which strips surrounding quotes (needed because Docker `--env-file` keeps them). Env vars are organized by migration phase — check `.env.example` for the phase each one belongs to before adding new config.
- `auth.py` — Supabase JWT verification (`get_current_user_id`), tries ES256-via-JWKS first, falls back to legacy HS256-via-shared-secret. When `AUTH_REQUIRED` is unset, falls back to `DEFAULT_USER_ID` for local single-user dev.
- `routers/` — one file per resource (`dashboard`, `sold`, `active`, `lots`, `pricing`, `pipeline`, `promotion`, `ebay`). `active.py` is the largest: listing list/detail, per-listing and bulk price apply (which write `price_change_log` and, via `trading_api.revise_price_with_best_offer`, also move the listing's Best Offer auto-accept/auto-decline thresholds), per-card refresh, price-change history (`GET /active/price-changes`), and the analytics aggregations. `pricing.py` and `promotion.py` are still mounted but no frontend page currently calls them.
- Best Offer thresholds can't move in the same Trading API call as price — eBay validates each side against what's currently live, so `revise_price_with_best_offer` sequences two `ReviseFixedPriceItem` calls, moving whichever side gains slack first (thresholds down before a price cut, price up before a threshold raise). Getting the order wrong is rejected outright, not silently ignored.
- `routers/lots.py` — buying lots, grouped by the SKU already stamped on listings and orders (`L0030`, `L0041`, …). `PULL`, `NONTCG` and rows with no SKU aren't purchased lots and are excluded (`EXCLUDED_SKUS`) — but the filter is applied *after* the per-line allocation below, never before, or a mixed order's whole net lands on the one real lot in it. Only the purchase cost is stored (`lots`, migration 0008); units sold, net proceeds, live items and listed value are aggregated on read. **eBay puts order-level money on only one row of a multi-item order**, so `SUM(order_earnings)` grouped by SKU credits a whole mixed order to one lot and gives the others zero — the query instead splits each order's net across its lines by their share of order item value, which conserves exactly. Any new per-SKU or per-card money aggregate has the same trap.
- `services/ebay_client.py`, `ebay_oauth.py` — per-user eBay OAuth (PKCE). Refresh tokens are Fernet-encrypted at rest (`EBAY_TOKEN_ENCRYPTION_KEY`).
- SQL is Postgres-flavored (the migration off SQLite is done at the DB layer); don't reintroduce SQLite-specific syntax (`?` params, `CAST(x AS REAL)`, `strftime`) in new queries — see the mapping rules in `docs/SOFTWARE_PLAN.md` §6.3 if porting old SQL.

### Dashboard frontend
React 19 + TypeScript + Vite, Tailwind v4, TanStack Query, react-router-dom v7, Recharts, Supabase JS client for auth.
- `lib/api.ts` — API client, base URL from `VITE_API_BASE` (defaults to local backend).
- `lib/auth.tsx` / `auth-context.ts` — Supabase session provider; `App.tsx` gates all routes except `/login` behind a `Protected` wrapper.
- `lib/theme.tsx` — light/dark theme context; components must handle both.
- `pages/` — one file per route: Dashboard, SoldOrders, ActiveListings, ListingDetail, Lots (`/lots`, per-SKU cost/profit with an inline cost editor), PriceLog (`/log`, reads `GET /active/price-changes`), Settings, Login. (Standalone Pricing and Promotions pages were removed; that data now lives on the Active Listings and Dashboard pages.)
- `components/shared/` — `DataTable`, `KpiCard`, `Skeleton`, `StageRefreshButton` (the page-level refresh control wired to `stage_runner`).
- Linting is oxlint (`.oxlintrc.json`), not ESLint.

## Working across the pipeline/dashboard boundary

Pipeline scripts write to Excel + local SQLite; the dashboard reads Postgres and re-syncs from Excel on each startup/trigger. If you change a column name or add a field in the Excel sheets (`get_active.py`, `append_sold_orders.py`), you must also update the corresponding column-mapping dict in `dashboard/backend/services/excel_sync.py` (`_SOLD_COLUMNS`, `_ACTIVE_COLUMNS`) or the new field silently won't reach the dashboard.

Similarly, a field added to the Excel path usually needs adding to the OAuth path (`services/ebay_data.py`) too, or connected users won't get it.

## Git and Commit Conventions

- NEVER include Claude/AI-related comments, attributions, or signatures in PR descriptions, commit messages, code comments, or any content pushed to GitHub.
- Do not include "Co-Authored-By" lines.
