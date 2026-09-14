# EbayPrice — Software Plan & Architecture Document

## 1. Overview

**Current state:** Local-only Pokemon card eBay seller toolchain. Python scripts pull data from the user's eBay account + Google Drive workbook, analyze card prices, and a React + FastAPI dashboard displays it. All data lives in one SQLite file.

**Target state:** Multi-user SaaS where each user connects their own eBay account (eBay API per user). Data in Supabase (Postgres + Auth + Row Level Security), dashboard deployed remotely, workbook dependency removed.

---

## 2. Current Architecture

```
+--------------------------------------------------------------+
|  scripts/main.py  (orchestrator, logged to logs/main.log)    |
|   append_sold_orders.py    -> sold orders + earnings          |
|   get_active.py            -> active listings from eBay       |
|   price_active_listings.py -> price_snapshots + sold_listings |
|   avg_active_price.py      -> active_price_snapshots +        |
|                              listing_positions               |
+------------------+-------------------------------------------+
                   |  (eBay OAuth in .env: EBAY_APP_ID, EBAY_SECRET,
                   |   EBAY_DEV_ID, REFRESH_TOKEN - single account)
+------------------v-------------+   +--------------------------+
|  db/pokemon_prices.db          |   | H:\My Drive\ebay\        |
|  (SQLite, 7 tables)            |<--| ebay_sold_orders.xlsx    |
+------------------+-------------+   +--------------------------+
                   |
+------------------v-------------+   +--------------------------+
|  FastAPI backend :8000         |   |  React frontend (Vite)   |
|  /api/v1/* (6 routers)         |   |  5 pages, api.ts ->      |
|  excel_sync on startup         |   |  http://127.0.0.1:8000   |
+--------------------------------+   +--------------------------+
```

**eBay API usage today** (`src/ebaypricer/`):
- `auth.py` — `get_access_token()`: refresh-token grant (writes token to `.env`); `get_ebay_token()`: client-credentials grant (cached) for Browse API
- `trading_api.py` — Trading API (XML `GetSellerTransactions`-style), single account
- `browse_api.py` — public marketplace search: outlier filtering (2-sigma), `BUYING_OPTIONS="FIXED_PRICE"`, `EXCLUDED_TERMS="-PSA -BGS -CGC -SGC -graded -slab"`, max 5 query words
- `marketing_api.py` — promotions; `cards.py` — card-name mapping (caches in `data/`)
- `finances.py` — per-order earnings from gross (`totalFeeBasisAmount`) minus fees minus debits; helpers `_closest_by_date`
- `excel.py` — workbook currency columns
- `paths.py` — DB/env/cache paths

---

## 3. Current Database Schema (`db/pokemon_prices.db`, SQLite)

### 3.1 `staging_sold_orders` — 525 rows (all columns TEXT; drop/recreate on every sync)
| Column | Meaning |
|---|---|
| Order ID | `11-11963-30970` |
| Item ID | eBay item number |
| Sale Date | `2024-08-19` |
| Buyer | username |
| Item Title | |
| Quantity, Item Price, Shipping, Order Total, Total eBay Fees, Order Earnings | all TEXT, order-level values repeated per line item (cause of past double-count bug) |
| SKU, Card, col_13 | col_13 always null (junk) |

### 3.2 `staging_active_listings` — 187 rows (all TEXT, drop/recreate every sync)
21 real columns: Item ID, Title, Card, Condition, SKU, Price, Shipping Charge, Ad Rate (`5%`), Watchers, Days Listed, Start Date, Quantity, Estimated Fees, Estimated Net, Recent Sold Avg, Price vs Sold Avg, Recent Sold Count, Last Checked, Active Avg (Top 5), Price Accuracy (raw, e.g. `-0.492`), Search Position. **Plus junk:** `col_21`..`col_48` and a `Last updated: ...` column (all null).

### 3.3 `price_snapshots` — 3,723 rows (sold-marketplace history, shared)
`id` INTEGER PK, `card_query` TEXT, `snapshot_date` TEXT, `sample_size` INT, `avg_price` REAL, `median_price` REAL, `min_price` REAL, `max_price` REAL, `std_dev` REAL, `weighted_avg` REAL; UNIQUE auto-index (`card_query, snapshot_date`).

### 3.4 `active_price_snapshots` — 2,827 rows (shared)
`id` PK, `card_query`, `snapshot_date`, `sample_size`, `avg_price`, `min_price`, `max_price`; UNIQUE (`card_query, snapshot_date`).

### 3.5 `sold_listings` — 13,850 rows (marketplace sold items, shared)
`id` PK, `item_id` (`v1|287436153998|0`), `card_query`, `title`, `price` REAL, `currency`, `condition`, `listing_type`, `sold_date` (ISO with T/Z), `url`, `pulled_at`.

### 3.6 `listing_positions` — 376 rows (search-rank history — **user-owned**)
`id` PK, `item_id`, `card_query`, `snapshot_date`, `position` INT, `search_size` INT; UNIQUE (`item_id, card_query, snapshot_date`).

### 3.7 `inventory_value_history` — 2 rows (user-owned)
`snapshot_date` TEXT PK, `total_value` REAL, `total_listings` INT. Upserted each sync.

---

## 4. Current API (FastAPI, `/api/v1`)

| Router | Endpoints |
|---|---|
| `dashboard.py` | `GET /dashboard/kpis` — monthly KPIs (per-order deduped ship/fees), 30-day zero-filled trends, top items |
| `sold.py` | `GET /sold/list` (page/card/dates/sort), `/sold/summary` (deduped per order; earnings = revenue - fees), `/sold/trends`, `/sold/by-card` |
| `active.py` | `/active/list` (card/sort incl. numeric CAST), `/item/{item_id}`, `/summary`, `/by-card-value`, `/value-buckets`, `/value-trend`, `/days-distribution` |
| `lots.py` | `GET /lots` (per-SKU cost, sold net, listed value, profit), `PUT /lots/{sku}` (upsert cost) |
| `active.py` (cont.) | `PUT /active/item/{id}/card` — hand-set the catalog match, locked against sync re-derivation (migration 0013) |
| `inventory.py` | `GET /inventory` (unlisted pile, filters + cached value), `POST /inventory`, `PUT|DELETE /inventory/{id}`, `POST /inventory/bulk-update` (only the fields sent; absent = leave, null = clear), `POST /inventory/bulk-delete`, `POST /inventory/{id}/archive|unarchive`, `POST /inventory/bulk-archive` |
| `pricing.py` | `/pricing/comparisons`, `/snapshots`, `/cards/{card_name}` (fuzzy match, 10 recent sold) |
| `pipeline.py` | `/pipeline/status` (in-memory state + log mtime), `/logs`, `POST /run` (subprocess `scripts/main.py`) |
| `promotion.py` | promotions endpoints |
| `main.py` | startup: syncs workbook -> staging tables |

**SQLite-specific SQL everywhere:** `CAST(x AS REAL)`, `date('now', '-29 days')`, `strftime('%Y-%m', ...)`, `?` params, quoted mixed-case column names, `PRAGMA query_only` in `get_db()`.

## 5. Current Frontend (React 18 + Vite + TS)

- `src/lib/api.ts` — `BASE = 'http://127.0.0.1:8000/api/v1'` (hardcoded)
- `App.tsx` routes: `/dashboard`, `/sold`, `/active`, `/active/:itemId` (plus Pricing/Promotions pages; no auth anywhere)
- Pages: `DashboardPage`, `SoldOrdersPage`, `ActiveListingsPage`, `ListingDetailPage`, `PricingPage`, `PromotionsPage`
- Shared: `DataTable`, `KpiCard`, `Skeleton`, `types/index.ts`

---

## 6. Target: Supabase Schema (Postgres)

**Auth:** Supabase Auth (email/password). RLS pattern: user-owned tables use `user_id = auth.uid()`; shared tables read for any authenticated user, write via service role only.

### 6.1 User-owned tables (all get `user_id uuid NOT NULL REFERENCES auth.users(id)` + RLS)

**`sold_orders`** (from `staging_sold_orders`) — PK (`user_id, order_id, item_id`)
`order_id text, item_id text, sale_date date, buyer text, item_title text, quantity int, item_price numeric(10,2), shipping numeric(10,2), order_total numeric(10,2), total_fees numeric(10,2), order_earnings numeric(10,2), sku text, card text`

**`active_listings`** (from `staging_active_listings`, junk cols dropped) — PK (`user_id, item_id`)
`item_id text, title text, card text, condition text, sku text, price numeric(10,2), shipping_charge numeric(10,2), ad_rate numeric(5,2), watchers int, days_listed int, start_date date, quantity int, estimated_fees numeric(10,2), estimated_net numeric(10,2), recent_sold_avg numeric(10,2), price_vs_sold_avg numeric(10,2), recent_sold_count int, last_checked date, active_avg_top5 numeric(10,2), price_accuracy numeric(10,4), search_position int`

**`inventory_value_history`** — PK (`user_id, snapshot_date`); `total_value numeric, total_listings int`

**`listing_positions`** — PK (`user_id, item_id, snapshot_date`); + `card_query text, position int, search_size int`

**`ebay_connections`** — PK (`user_id`); `ebay_user_id text, refresh_token text (encrypted), scopes text, token_issued_at timestamptz, token_expires_at timestamptz, last_synced_at timestamptz, sync_status text`

**`price_change_log`** (migration 0005) — `id` PK; `user_id uuid, item_id text, old_price numeric(10,2), new_price numeric(10,2), source text ('single'|'bulk'), changed_at timestamptz`. Append-only history of price revisions this app applied to live eBay listings — `active_listings.price` is overwritten in place, so nothing else records what a listing used to cost. Also drives the reprice cooldown: `suggested_price.py` declines to suggest for `REPRICE_COOLDOWN_DAYS` (5) after a change lands, so the model doesn't ask to re-edit a price that hasn't had time to work. Only *applied* changes are logged — a revision eBay rejected must not start a cooldown.

**`inventory`** (migration 0011; `manual_value` added in 0012, `archived_at` in 0014) — `id` PK; `user_id uuid, name text, card_query text, set_name text, number text, condition text, quantity int (check > 0), location text, sku text, cost numeric(10,2) *(per unit)*, manual_value numeric(10,2) *(per unit, hand-stated; wins over comps, condition multiplier NOT applied)*, notes text, created_at/updated_at timestamptz`. Cards owned but not yet listed — the gap between a lot being bought and its cards reaching `active_listings`. Unlike every other table here it is **entirely hand-entered**: eBay has no idea what is in a box on the desk, so nothing syncs, overwrites or reconciles it. Surrogate id rather than a natural key because the same card in the same condition can sit in two boxes and both rows are real. There is deliberately **no "listed" status flag** — a card that goes up for sale has its row deleted or decremented and `active_listings` takes over; two tables both claiming to know whether something is listed is how they end up disagreeing. `card_query` is the same catalog identity used by `active_price_snapshots`, which is what lets the page show a value; it is nullable, and sealed/bulk rows simply have none. Value is read from the **shared snapshots only and never researched in the request** — a pile can hold hundreds of cards and one page load would otherwise fire hundreds of Browse calls.

**`lots`** (migration 0008; `title` added in 0009) — PK (`user_id, sku`); `title text, cost numeric(10,2), purchased_at date, source text, notes text, updated_at timestamptz`. The purchase cost of a buying lot, keyed by the SKU already stamped on its listings and orders (`PULL`, `NONTCG` and rows with no SKU are not purchased lots and are excluded from the page). Deliberately holds *only* what can't be derived — units sold, net proceeds, live items and current listed value are aggregated on read from `sold_orders` + `active_listings` by `routers/lots.py`, so a lot appears on the page as soon as its SKU exists in the data and there is no "create the lot first" step. Note the multi-item-order caveat recorded there: eBay reports order-level money on one row per order, so per-SKU net has to be allocated across the order's lines, never summed directly.

### 6.2 Shared tables (RLS: `authenticated` can SELECT; writes only via service role)
`price_snapshots`, `active_price_snapshots`, `sold_listings` — same columns as Section 3, typed (`date`, `numeric`, `timestamptz` for `pulled_at`), UNIQUE constraints preserved. `card_queries` (from `cards.py` cache) optional.

### 6.3 SQLite -> Postgres mapping rules
- `TEXT` price/quantity cols -> `numeric(10,2)` / `int`; dates -> `date`; ISO timestamps -> `timestamptz`
- `CAST(x AS REAL)` -> `x::double precision`; `date('now', '-N days')` -> `CURRENT_DATE - INTERVAL 'N days'`; `strftime('%Y-%m', c)` -> `to_char(c, 'YYYY-MM')`
- `?` -> `%s`; `INSERT OR REPLACE` -> `ON CONFLICT ... DO UPDATE`; quoted `"Column"` casing preserved in PG (quoted identifiers are case-sensitive — keep the quotes)

---

## 7. Migration Plan — Phases

| Phase | Work |
|---|---|
| **1. Platform** | Supabase project; DDL for Section 6 schema + RLS policies; `get_db()` -> `psycopg` pool (`database.py`), dialect fixes in all 6 routers; JWT auth dependency (`auth.uid()`); config from env |
| **2. Data migration** | Python script: SQLite -> Supabase (shared tables + your rows); staging tables skipped (rebuilt by sync) |
| **3. Frontend auth** | `supabase-js` login/register, guarded routes, `api.ts` -> remote base + `Authorization: Bearer` token |
| **4. Deploy** | FastAPI + built frontend on one host; env vars (Supabase URL, anon/service keys, JWT secret) |
| **5. eBay OAuth per user** | `ebay_connections` + PKCE flow (redirect -> callback -> refresh token); reuse `auth.py` grant logic per-user; sell/fulfillment orders + sell/finances transactions in `ebay_client.py` |
| **6. Per-user sync** | Rewrite `append_sold_orders.py`/`excel_sync.py` into `process_ebay_data(user_id, ...)`; scheduled per-user sync; keep shared snapshot jobs server-side |
| **7. Retire workbook** | Drop Drive workbook dependency; note derived cols (Search Rank, Price Accuracy, spreads) recomputed server-side from shared snapshots |

**Key risks:** eBay production app approval (user action, days); per-user refresh tokens must be encrypted; app-level eBay rate limits shared across users; `sold_listings.item_id` format differs from API item IDs (keep as-is, it is opaque); dashboard SQL touches ~7 files.
