# CLAUDE.md

## What this is

An automated eBay selling pipeline for a Pokemon card business, plus a dashboard to view the data. Two halves that share a database but run independently:

1. **Pipeline** (`src/ebaypricer/` + `scripts/`) — Python scripts that talk to eBay's Trading/Browse/Marketing/Finances APIs, do pricing research, and read/write an Excel workbook (`H:\My Drive\ebay\ebay_sold_orders.xlsx`, path in `EBAY_EXCEL_PATH`) as the bookkeeping source of truth. Runs hourly via Windows Task Scheduler (`scripts/run_hourly.ps1`).
2. **Dashboard** (`dashboard/backend` FastAPI + `dashboard/frontend` React/Vite) — reads from Postgres/Supabase, displaying sold orders, active listings, and pricing. On startup it syncs the Excel workbook into Postgres (`services/excel_sync.py`).

The project is mid-migration from a single-user local SQLite tool to a multi-user Supabase-backed SaaS. **Read `docs/SOFTWARE_PLAN.md` before touching schema, auth, or the migration path** — it documents the current vs. target architecture, the full Postgres schema, and the phase plan. Treat it as living design doc, not historical record; update it when a phase completes or the plan changes.

A third piece, `ebay-defaults-extension/`, is a standalone Chrome extension (vanilla JS, no build step) for filling eBay listing form defaults — unrelated to the Python/dashboard code.

## Commands

### Pipeline (Python, from repo root)
```bash
pip install -e .                        # required: installs src/ebaypricer as editable package
python scripts/main.py                  # full pipeline, sequential, logs to logs/main.log
python scripts/main.py --dry-run        # preview promotion changes only
python scripts/gen_access_token.py      # one-time OAuth consent flow -> writes tokens to .env
python scripts/price_active_listings.py --force   # bypass daily SQLite cache
```
No test suite exists in this repo currently.

### Dashboard backend (FastAPI, from repo root)
```bash
python -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend commands are the standard `npm run` scripts in `dashboard/frontend/package.json`.

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

**eBay has no sold-comps API here.** The Browse API silently ignores the `soldDate` filter and returns ordinary active listings, so anything labeled "sold" from Browse is wrong. Sold-side research uses TCGdex/TCGPlayer market price via `ebaypricer.cards.lookup_market_price` (a single-point sample, `sample_size=1`), not eBay. Real sold comps would need eBay's Marketplace Insights API, which is restricted-access and not on this app's scopes. Don't "fix" this by reintroducing a Browse sold search. Active-listing search via Browse *is* real — but its results are **not** usable as-is: Browse matches on words, not card identity, so a pool arrives mixed with graded slabs, multi-card lots, print-error one-offs, foreign/Japanese prints and wrong prints. `src/ebaypricer/comp_filter.py` screens them out before any aggregate is computed, and records what it dropped in `active_price_snapshots.pool_quality` (migration 0010). Add a new contamination rule there, not in the aggregation code.

### Suggested price model
`dashboard/backend/services/suggested_price.py` is the single canonical pricing model, and it is **pure** — no DB, no network, no clock; callers pass clock-derived inputs in rather than letting the module read the time. Two prohibitions that outlive any detail: **don't reintroduce pricing math in the frontend** (a client-side `computeRecommendedPrice` used to produce different numbers on the list page vs. the detail page), and don't make the module impure to get at "now".

Everything else — the anchor pipeline, each guardrail and status, which inputs feed it, and what must never be reintroduced — lives in the **`ebay-pricing-rules` skill**, which loads on demand, plus the tuning-constant comments at the top of `suggested_price.py`. Read the skill before changing pricing logic, explaining a suggested price, or adding a pricing input. It is deliberately the only prose copy of the model, so nothing here can drift out of sync with the code.

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
`scripts/main.py` chains five sub-scripts over the Excel workbook. The per-script
detail lives in `scripts/CLAUDE.md`, which loads when you work in that directory.

Shared library in `src/ebaypricer/`: `auth.py` (OAuth token refresh, persisted to `.env`), `trading_api.py`, `browse_api.py`, `marketing_api.py`, `finances.py`, `cards.py` (Pokemon card DB, fuzzy matching, TCGdex market price, `card_identity()`; caches in `data/`), `comp_filter.py` (pure comp-pool screening — see above), `listing_economics.py`, `excel.py` (workbook styling), `paths.py` (all file paths — `PROJECT_ROOT`, `DB_PATH`, cache files; import from here rather than hardcoding paths).

Local SQLite lives at `db/pokemon_prices.db`. Some tables are shared marketplace data (`price_snapshots`, `active_snapshots`, `sold_listings`), rebuilt/appended incrementally; others mirror the workbook and get dropped/recreated each sync — see `docs/SOFTWARE_PLAN.md` §3 for the full schema and which tables are "shared" vs "user-owned" in the Supabase target.

### Dashboard backend
FastAPI app in `dashboard/backend/main.py`. On startup: reconciles orphaned `job_runs`, starts the per-user sync scheduler if any eBay connections exist, then syncs the Excel workbook into Postgres. Serves the built frontend (`dashboard/frontend/dist`) directly when present, with SPA fallback routing — so in single-host/prod deployment there's one process on :8000.

- `database.py` — psycopg3 connection pool (`get_db()`), defaults to read-only transactions. The pool is small (5); never take a second connection while holding one (pass data down instead — see `update_active_listing_derived_columns`).
- `config.py` — all env vars, read through `_env()` which strips surrounding quotes (needed because Docker `--env-file` keeps them). Env vars are organized by migration phase — check `.env.example` for the phase each one belongs to before adding new config.
- `auth.py` — Supabase JWT verification (`get_current_user_id`), tries ES256-via-JWKS first, falls back to legacy HS256-via-shared-secret. When `AUTH_REQUIRED` is unset, falls back to `DEFAULT_USER_ID` for local single-user dev.
- `routers/` — one file per resource (`dashboard`, `sold`, `active`, `lots`, `pricing`, `pipeline`, `promotion`, `ebay`). `active.py` is the largest: listing list/detail, per-listing and bulk price apply (which write `price_change_log` and call `trading_api.revise_item_price`), per-card refresh, price-change history (`GET /active/price-changes`), and the analytics aggregations. `pricing.py` and `promotion.py` are still mounted but no frontend page currently calls them.
- **Applying a price changes the price and nothing else.** Best Offer auto-accept and minimum-offer thresholds are the seller's to set on the listing; repricing must not read, write, or derive them. `revise_best_offer_thresholds` and `revise_price_with_best_offer` were deleted from `trading_api.py` for this reason, along with `OFFER_THRESHOLD_PCT` in `active.py` (which pinned both to 90% of the new price) and the bulk result's `"partial"` status (price landed, thresholds didn't — no longer a reachable state). Don't reintroduce any of it. If a deliberate, separate offer-threshold action is ever wanted, note that eBay validates each side against what's currently live, so price and thresholds can never move in one `ReviseFixedPriceItem` call — the ordering rules are written up in `.claude/skills/ebay-listing-dry-run/SKILL.md`.
- `routers/lots.py` — buying lots, grouped by the SKU already stamped on listings and orders (`L0030`, `L0041`, …). `PULL`, `NONTCG` and rows with no SKU aren't purchased lots and are excluded (`EXCLUDED_SKUS`) — but the filter is applied *after* the per-line allocation below, never before, or a mixed order's whole net lands on the one real lot in it. Only the user-entered fields are stored (`lots`, migration 0008: title, cost, purchase date, source, notes — `title` came later in 0009, so both the read and the write degrade if that hasn't been run: costs still save and only a supplied title is refused). Units sold, net proceeds, live items and listed value are aggregated on read. **eBay puts order-level money on only one row of a multi-item order**, so `SUM(order_earnings)` grouped by SKU credits a whole mixed order to one lot and gives the others zero — the query instead splits each order's net across its lines by their share of order item value, which conserves exactly. Any new per-SKU or per-card money aggregate has the same trap. `GET /lots/{sku}` drills into one lot's sold and active listings and shares that allocation through `_SOLD_LINES_CTE`, so a sold line shows its allocated share of its order's net and the rows still sum to the figure the list page shows.
- `services/ebay_client.py`, `ebay_oauth.py` — per-user eBay OAuth (PKCE). Refresh tokens are Fernet-encrypted at rest (`EBAY_TOKEN_ENCRYPTION_KEY`).
- SQL is Postgres-flavored (the migration off SQLite is done at the DB layer); don't reintroduce SQLite-specific syntax (`?` params, `CAST(x AS REAL)`, `strftime`) in new queries — see the mapping rules in `docs/SOFTWARE_PLAN.md` §6.3 if porting old SQL.

### Dashboard frontend
React 19 + TypeScript + Vite, served by FastAPI in prod. Route map, shared
components, the light/dark requirement, oxlint, and the "never compute a price in
the frontend" rule are in `dashboard/frontend/CLAUDE.md`, which loads when you work
in that directory.

## Working across the pipeline/dashboard boundary

Pipeline scripts write to Excel + local SQLite; the dashboard reads Postgres and re-syncs from Excel on each startup/trigger. If you change a column name or add a field in the Excel sheets (`get_active.py`, `append_sold_orders.py`), you must also update the corresponding column-mapping dict in `dashboard/backend/services/excel_sync.py` (`_SOLD_COLUMNS`, `_ACTIVE_COLUMNS`) or the new field silently won't reach the dashboard.

Similarly, a field added to the Excel path usually needs adding to the OAuth path (`services/ebay_data.py`) too, or connected users won't get it.

## Git and Commit Conventions

- NEVER include Claude/AI-related comments, attributions, or signatures in PR descriptions, commit messages, code comments, or any content pushed to GitHub.
- Do not include "Co-Authored-By" lines.
