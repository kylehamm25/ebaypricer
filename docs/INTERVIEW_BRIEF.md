# EbayPrice — Interview Brief

Everything needed to explain this project confidently: what it is, how it's built, why the
design decisions were made, and where the honest weak spots are.

---

## 1. The 30-second pitch

> "It's an automated pricing and bookkeeping platform for a high-volume eBay Pokémon card
> business. It pulls sold orders, active listings, and fee data out of eBay's APIs, researches
> what each card is actually worth on the open market, computes a recommended price per
> listing, and can push price revisions back to live eBay listings — in bulk. There's a
> React dashboard on top of it, and it runs itself on a background scheduler.
>
> It started as a single-user Python script suite writing to an Excel workbook and a local
> SQLite file. It's now most of the way through a migration to a multi-tenant SaaS on
> FastAPI + Supabase Postgres, with per-user eBay OAuth and row-level security."

The two-sentence version if they want it shorter: *"An eBay seller-automation tool for a
Pokémon card business — data pipeline plus dashboard. Mid-migration from a local single-user
script to a multi-tenant Supabase-backed web app."*

**Scale:** ~190 active listings, ~525 sold orders, ~3,700 sold-price snapshots, ~2,800
active-price snapshots, ~13,900 individual marketplace comps. Six external APIs. ~11,000
lines of first-party Python/TypeScript.

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Pipeline / scripts | Python 3.12+, `requests`, `openpyxl`, `rapidfuzz` |
| Backend API | FastAPI, Uvicorn, Pydantic |
| Database (target) | PostgreSQL via Supabase (psycopg3 + `psycopg_pool`) |
| Database (legacy) | SQLite (`db/pokemon_prices.db`), still used by the legacy pipeline path |
| Auth | Supabase Auth — JWT verified server-side with PyJWT (ES256 via JWKS, HS256 fallback) |
| Secrets at rest | `cryptography.fernet` — eBay refresh tokens encrypted before storage |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, TanStack Query v5, react-router-dom v7, Recharts, `@supabase/supabase-js` |
| Linting | oxlint (Rust-based, not ESLint) |
| Packaging / deploy | Docker multi-stage (Node 22 → Python 3.13-slim), AWS ECS Fargate + ECR, Secrets Manager, ALB |
| Scheduling | Windows Task Scheduler (`run_hourly.ps1`) for the legacy pipeline; an in-process daemon thread in the backend for everything else |
| Extra | Chrome extension (Manifest V3, vanilla JS, no build step) |

**External APIs consumed (6):**
- eBay **Trading API** (XML/SOAP-ish) — sold orders, active listings, item condition, *price revisions*
- eBay **Browse API** (REST) — searching live marketplace listings for competitor comps
- eBay **Marketing API** — Promoted Listings campaigns, ads, bulk bid updates
- eBay **Finances API** — real per-order fee and payout data
- eBay **Fulfillment API** — per-user order fetch on the OAuth path
- eBay **Identity/OAuth** — token grants + `userinfo`

Plus three non-eBay data sources: **TCGdex** (card market prices), the **PokemonTCG/pokemon-tcg-data**
GitHub dataset (~20k card records, cached locally), and **PokeAPI** (sprite images for the UI).

---

## 3. Architecture

Two halves that share a database but run independently.

```
                      ┌───────────────────────────────────────────┐
                      │              eBay APIs (6)                │
                      │  Trading · Browse · Marketing · Finances   │
                      │        Fulfillment · Identity/OAuth        │
                      └───────┬───────────────────────┬───────────┘
                              │                       │
        LEGACY PATH (single account, .env token)      │  MODERN PATH (per-user OAuth)
                              │                       │
   ┌──────────────────────────▼──────────┐            │
   │  scripts/main.py (orchestrator)      │           │
   │   1 append_sold_orders.py            │           │
   │   2 get_active.py                    │           │
   │   3 price_active_listings.py         │           │
   │   4 avg_active_price.py              │           │
   └───────┬──────────────────┬───────────┘           │
           │                  │                       │
   ┌───────▼──────┐   ┌───────▼────────┐              │
   │ Excel .xlsx  │   │ SQLite         │              │
   │ (Google Dr.) │   │ pokemon_prices │              │
   └───────┬──────┘   └───────┬────────┘              │
           │  excel_sync.py   │ pipeline_runner.py    │
           └────────┬─────────┘                       │
                    │                                 │
          ┌─────────▼─────────────────────────────────▼──────────┐
          │        FastAPI backend  (dashboard/backend)          │
          │  routers/ ×7   services/ ×8   auth.py   database.py  │
          │  + background scheduler thread (4 job cadences)      │
          └─────────┬────────────────────────────────┬───────────┘
                    │                                │
          ┌─────────▼──────────┐          ┌──────────▼──────────┐
          │ Supabase Postgres  │          │  React SPA (Vite)   │
          │ 12 tables + RLS    │          │  served by FastAPI  │
          │ Supabase Auth      │◄─────────┤  in prod (one host) │
          └────────────────────┘   JWT    └─────────────────────┘
```

### Why two paths exist
The legacy path is the original working system: it treats an Excel workbook on Google Drive as
the bookkeeping source of truth, because the business owner actually reads and edits that
workbook. The modern path (`services/ebay_data.py`) replaces it entirely for any user who
connects their own eBay account via OAuth — no workbook required. Both write into the same
Postgres tables, so the dashboard doesn't care which produced the data. The migration plan
(`docs/SOFTWARE_PLAN.md` §7) retires the workbook once the OAuth path fully covers it.

This is a good thing to volunteer in an interview: **it's a strangler-fig migration.** New
system built alongside the old one, sharing a data store, with the old one deleted path by path
rather than in a big-bang rewrite.

---

## 4. End-to-end data flow

**Ingest (per user, every 6h or on demand):** `services/ebay_data.py::sync_user_ebay_data()`
1. Get a per-user eBay access token (refresh grant, decrypted from Postgres, cached in memory).
2. `fetch_sold_orders()` → Trading API XML → line-item rows.
3. Dedupe by `(Item ID, Sale Date)`; merge in real fee/earnings data from the Finances API
   (fetched with a 15-day lookback overlap, since fees settle after the sale).
4. Blank order-level columns on continuation rows of multi-item orders (one shipping charge
   per order, not per line — this was the source of a real double-counting bug).
5. `fetch_active_listings()` → enrich each with condition, shipping-profile cost, and a tiered
   fee/net estimate.
6. Fuzzy-match every title to a canonical card name (`ebaypricer/cards.py`).
7. Upsert into `sold_orders` / `active_listings`; **prune** active listings eBay no longer
   returns (they sold or ended) — but only if eBay returned a non-empty set, so a transient
   API failure can't wipe the table.
8. Recompute inventory value, write `inventory_value_history`, recompute suggestions.

**Research (shared across all users, every 6h):** `services/price_research.py::run_shared_price_research()`
1. Collect the union of every card any user currently has listed.
2. Per card: fetch a market price from TCGdex → `price_snapshots`; search live eBay listings
   via the Browse API → `active_market_listings` + `active_price_snapshots`.
3. Determine each listing's **search rank** — where it appears in eBay's own results for its card.
4. Run the suggested-price model and write the derived columns onto *every* user's rows for
   that card.

Key point worth making: research is **per-card, not per-user.** Two sellers listing the same
card share one API call and one snapshot row. That's what makes the cost model work as user
count grows — eBay rate limits are per *application*, not per user.

**Act:** the user reviews suggestions in the dashboard and applies them — one listing at a
time, or in bulk (`POST /active/bulk-price`, up to 100/request, chunked client-side). Applied
changes go to eBay via `ReviseFixedPriceItem` and are logged to `price_change_log`.

---

## 5. Database schema (Postgres / Supabase)

**User-owned** (every row carries `user_id uuid` → `auth.users(id)`, RLS `user_id = auth.uid()`):
- `sold_orders` — PK `(user_id, order_id, item_id)`
- `active_listings` — PK `(user_id, item_id)`; 21 base columns + 3 suggestion columns
- `inventory_value_history` — daily total inventory value snapshot
- `listing_positions` — daily search-rank history per listing
- `price_change_log` — append-only audit of applied price revisions
- `ebay_connections` — one row per user; encrypted refresh token, scopes, sync status
- `ebay_oauth_states` — short-lived OAuth state (10 min TTL), service-role only

**Shared marketplace data** (RLS: any authenticated user can `SELECT`, writes via service role only):
- `price_snapshots` — daily market price per card
- `active_price_snapshots` — daily competitor aggregate per card (avg/min/max/**p25**)
- `sold_listings`, `active_market_listings` — individual comps

**System:**
- `job_runs` — every background job's status/duration/detail (`jsonb`), nullable `user_id`
  meaning "shared/system job"

Five idempotent migrations in `db/migrations/`, each with a header comment explaining *why*
the change was made. RLS policies are declared alongside the tables.

**Interview note on RLS:** the backend connects as the service role, which *bypasses* RLS —
so RLS is defense-in-depth, not the primary access control. Every query in the routers filters
`WHERE user_id = %s` explicitly from the JWT `sub` claim. RLS is what protects the data if a
client ever talks to Supabase directly with an anon key.

---

## 6. Backend deep dive

**`main.py`** — lifespan startup: reconcile orphaned `job_runs`, start the scheduler if any
eBay connection exists, sync the workbook. Mounts the built frontend with SPA fallback so
production is a single process on one port.

**`database.py`** — psycopg3 connection pool (min 1, max 5), `dict_row` factory,
`prepare_threshold=None` (required: Supabase's pgBouncer in transaction mode doesn't support
prepared statements). `get_db()` defaults to `SET TRANSACTION READ ONLY` — you must opt in to
writes. Small detail, but it means a read path can't accidentally mutate.

**`auth.py`** — verifies the Supabase JWT. Tries ES256 against the project JWKS endpoint first
(current Supabase), falls back to HS256 with the shared secret (legacy). Returns the `sub`
claim as a UUID. When `AUTH_REQUIRED` is false it falls back to `DEFAULT_USER_ID` for local
single-user dev — the escape hatch that let the migration proceed before auth existed.

**`routers/` (7)** — `dashboard` (KPIs, month navigation, trends), `sold`, `active` (the big
one, 560 lines: listing CRUD, price revision, bulk revision, price-change history, several
aggregate/chart endpoints), `pricing`, `pipeline`, `promotion`, `ebay` (OAuth connect flow).

**`services/` (8)** — `ebay_oauth`, `ebay_client`, `ebay_data` (per-user sync), `price_research`
(shared research + the orchestration), `suggested_price` (the pricing model), `promotion_boost`,
`excel_sync`, `pipeline_runner`, `stage_runner`.

**Scheduler** — one daemon thread ticking every 60s with three independent cadences: legacy
pipeline (1h), per-user eBay sync (6h), price research (6h). Ad-rate boosting used to be a
fourth (24h) and was deliberately removed: it spends money, so it now happens only on an
explicit request. Each is
wrapped so one failing round can't kill the loop.

---

## 7. Frontend deep dive

React 19 + Vite + TypeScript, Tailwind v4, TanStack Query for all server state (no Redux —
there's essentially no client-side state worth a store).

**Routes:** `/login`, `/dashboard`, `/sold`, `/active`, `/active/:itemId`, `/settings`.
Everything except `/login` is behind a `<Protected>` wrapper that reads the Supabase session.

**Auth flow:** `AuthProvider` holds the Supabase session and subscribes to `onAuthStateChange`;
`lib/api.ts` attaches `Authorization: Bearer <access_token>` to every request.

Things worth pointing at:
- **Filter/sort/page state lives in the URL query string**, not `useState` — so navigating to a
  listing detail and back preserves your filters, and the view is linkable.
- The sidebar remembers the last full path (including query params) visited per section.
- **Bulk apply is review-then-confirm.** Selecting rows opens a review panel; nothing hits a
  live eBay listing without a second explicit click. Requests are chunked to the backend's cap.
- **No pricing logic in the client.** There's an explicit comment in `lib/utils.ts` explaining
  why: there used to be a `computeRecommendedPrice()` called from two pages with different
  inputs, so the same listing showed two different "suggested" prices. It was moved server-side
  and stored on the row; the client only *formats* the stored `basis` object into a tooltip.
  That's a genuinely good "bug taught me an architectural rule" story.

---

## 8. The interesting algorithms

### 8.1 Suggested price model (`services/suggested_price.py`)

One sentence: **price a fresh listing near what competitors are asking, and the longer it sits
unsold, the closer to the competitive floor it gets — adjusted for condition, then clamped by
guardrails.**

```
anchors → staleness/rank blend → condition multiplier → watcher pull → guardrails → rounding
```

- **Anchors:** `anchor_avg` = mean competitor asking price (the margin end); `anchor_floor` =
  **25th percentile** of competitor prices (the competitive end). p25 rather than min, because
  min is a single listing that survived a 2σ filter — one junk or wrong-print listing would
  otherwise set the floor for the whole card.
- **Staleness ramp:** weight goes 0 → 1 linearly between 30 and 180 days listed. Primary driver.
- **Search rank:** secondary, 20% share. Deliberately a minority input because the *direction*
  of the signal is arguable (bad rank might mean "cut to get seen," but good rank + no sale
  arguably means the price is the problem).
- **Condition multiplier:** Near Mint 1.0 → Damaged 0.35. It's a multiplier and *not* a comp
  filter, because eBay's Browse API returns a generic condition for raw cards — the comp pool
  is an unfilterable mixed-condition bag, so scaling by our own known grade is the only
  mechanism available.
- **Watcher pull:** watchers are a live demand signal the comp pool can't see. Pulls the target
  back toward the current price (saturating at 5 watchers / 60% pull) rather than pushing it
  further — a listing that's already getting attention shouldn't be repriced aggressively.
- **Guardrails, in this order:** change cap (25%, floored at $0.25, hard-capped at $2.00) →
  net floor → absolute floor ($0.99) → psychological rounding (.49/.99, or 5¢ steps under $2).
  **Order matters:** the change cap pulls toward the current price, so it must run *before* the
  lower bounds, or an already-underpriced listing gets capped back below the floor just enforced.
  Rounding runs last so the output lands on a real price ending rather than an arbitrary clamp
  boundary like $2.98.
- **Declines to suggest** when: comps < 3, within a 5-day reprice cooldown, or the title matches
  a print-defect/novelty keyword (holo bleed, swirl, miscut, error) — those trade on the defect,
  so ordinary comps say nothing about their value.

The module is **pure**: no DB, no network, no clock. It takes plain values and returns a
`Suggestion` carrying the price *plus every intermediate*, which gets persisted as
`suggested_price_basis` (jsonb). That's what makes the UI able to explain itself
("listed 94d · rank #23 · comps $2.10–$3.40 (12) · limited by max change per step") and what
makes the model trivially testable.

### 8.2 The reprice cooldown (`price_change_log`)

After a price change is applied, that listing gets no new suggestion for 5 days. Without it:
the comp pool barely moves day to day, the staleness ramp keeps climbing, and the change cap
turns one intended reprice into a slow ratchet of daily nudges. Only *applied* changes start a
cooldown — a revision eBay rejected must not.

### 8.3 Self-exclusion (a feedback loop bug)

eBay's search returns your own listings like any other result — that's in fact how search rank
is derived. So the competitor aggregates were partly measuring ourselves: cut a price → next
run reads that lower price as a competitor → pulls the average down → suggests cutting again.
Fixed by subtracting all known `item_id`s from the comp pool, with a fallback to the unfiltered
pool if exclusion leaves fewer than 3 comps (better a slightly polluted band than a garbage one
off 1–2 comps).

### 8.4 The "sold search doesn't exist" discovery

The original pipeline searched eBay's Browse API with a `soldDate:[...]` filter to get sold
comps. **That filter isn't real** — eBay silently ignores it and returns ordinary *active*
listings. Verified by comparing responses: identical item IDs to a plain active search, live
`buyingOptions` present, no `soldDate`/`itemEndDate` fields. So the system had been treating
active asking prices as realized sale prices the whole time. Real sold comps require eBay's
Marketplace Insights API, which is restricted-access. The fix: sold/market pricing now comes
from TCGdex (TCGPlayer market price) instead, and there's a prominent comment in
`browse_api.py` telling the next person not to recreate that search.

This is the single best story in the codebase to tell — it's a case of *not* trusting that an
API did what the code assumed, verifying empirically, and then documenting the negative result
so it can't recur.

### 8.5 Best Offer ordering constraint

eBay validates a price revision against what's *currently live* on the listing, never against
the other new value in the same request. So price and Best Offer thresholds can't move
together: cutting the price while the old higher auto-decline is live is rejected, and so is
raising thresholds before the higher price is live. Solution: sequence the two calls so
whichever side gains slack goes first — thresholds down before a price cut, price up before a
threshold raise. When the current price is unknown, assume a cut (the common case); a wrong
guess fails the first call harmlessly and the price still applies.

### 8.6 Card matching (`ebaypricer/cards.py`, 677 lines)

Mapping a free-text eBay title ("Charizard ex 223/197 SV Obsidian Flames SIR NM") to a
canonical card. Layered strategy: exact card-number regex → set-abbreviation expansion
(`obf` → obsidian flames, ~40 mappings) → promo-number patterns → rarity signals to
disambiguate multiple prints of the same name/number → `rapidfuzz` fuzzy fallback, guarded by a
"does this title even look like a Pokémon card" signal regex so unrelated listings don't get
force-matched. Backed by a ~20k-card local cache built from a GitHub dataset.

### 8.7 Promotion boost

Every 10 days a listing sits unsold, its Promoted Listings ad rate goes up 1%, capped at 5%
(3% for items over $50 — a percentage of a big number costs real money). Refuses to run against
Cost-Per-Click campaigns; batches up to 500 bid updates per Marketing API call.

---

## 9. Concurrency, reliability, and operational design

This is where to demonstrate seniority — it's the part most side projects skip.

- **Postgres advisory locks** (`pg_try_advisory_lock`) give single-runner guarantees *across
  processes*, not just threads: key 727001 legacy pipeline, 727002 price research, 727003 sold
  refresh, 727004 active refresh. Prod backend, a dev server, and a cron invocation can't
  double-run the same job. Paired with a local `threading.Lock` for the cheap in-process case.
- **`job_runs` as the observability layer.** Every job writes a `running` row on start and
  updates it on finish with a `jsonb` detail blob. `/pipeline/status` and the per-page refresh
  buttons read it. On startup, `reconcile_stale_job_runs()` marks anything still `running` as
  orphaned — otherwise a crash mid-run leaves the UI showing "running" forever, since nothing
  else revisits that row.
- **Wall-clock budget.** Price research stops after 45 minutes and lets the next run pick up the
  remaining cards. Individual calls are already bounded (15s timeouts, capped 429 retries), but
  a long tail of rate-limited cards could otherwise hold the advisory lock indefinitely and
  block every future run.
- **Audit writes never fail the real operation.** `price_change_log` and `job_runs` writes use
  their own connection and swallow exceptions — the price is already live on eBay by then, so
  failing to record history must not roll back the local state that reflects it.
- **Deliberate connection discipline.** `update_active_listing_derived_columns` takes
  `price_changes` as a parameter rather than querying for it, specifically because the caller
  already holds a write connection and grabbing a second from a 5-slot pool while holding one
  invites deadlock under concurrency.
- **Graceful degradation everywhere.** Promoted Listings ineligibility (403) is a normal
  per-user *outcome*, not a job failure, so a batch run across users keeps going. The cooldown
  lookup swallows failures so a deployment that hasn't run migration 0005 loses the cooldown,
  not the whole research run. `MarketingApiError` is raised rather than `sys.exit()` — that
  module is imported into a long-running server, where exiting would kill every user's session
  over one bad token.
- **Idempotency throughout.** Everything is `INSERT ... ON CONFLICT DO UPDATE`; every sync can
  be re-run safely.

---

## 10. Security

- eBay refresh tokens are **Fernet-encrypted at rest** in `ebay_connections`; the key comes from
  `EBAY_TOKEN_ENCRYPTION_KEY` (Secrets Manager in prod). Access tokens are never persisted —
  refreshed on demand and cached in memory for their lifetime.
- OAuth state is stored in Postgres with a 10-minute TTL (not in memory) so the connect flow
  survives restarts, redeploys, and multiple replicas. Consumed with a `DELETE ... RETURNING`,
  which makes it single-use atomically.
- Every data query filters by the `user_id` derived from a verified JWT. Ownership is checked
  before calling eBay on a price revision, even though eBay would reject a foreign item anyway.
- RLS as defense-in-depth (see §5).
- Secrets in ECS come from Secrets Manager, not the task definition's plaintext environment.
- The OAuth callback endpoint is intentionally unauthenticated — it's a browser redirect from
  eBay — and maps back to the user via the state token.

---

## 11. Deployment

- **Docker multi-stage:** Node 22 builds the frontend (`VITE_*` values are baked in at build
  time — worth flagging as a known constraint: changing the Supabase URL requires a rebuild,
  not just a restart), then Python 3.13-slim installs the backend and copies the built `dist/`.
  One container, one port, FastAPI serves both API and SPA.
- **AWS ECS Fargate:** `deploy/deploy.sh` builds → pushes to ECR tagged with the git short SHA →
  substitutes placeholders into `task-definition.json` → registers a revision → forces a
  service rollout. Health check hits `/`. ALB terminates TLS.
- **Local dev:** `start-dashboard.bat` (backend :8000 + Vite :5173) or `start-prod.bat`
  (single-host mode).
- `EBAY_EXCEL_PATH` is deliberately unset in the container — the backend checks whether the path
  exists and cleanly skips the legacy Excel round when it doesn't, so a container with no Google
  Drive mount just runs the OAuth path.
- CI: two GitHub Actions workflows for automated code review on PRs.

---

## 12. Migration status (the 7 phases)

| Phase | What | Status |
|---|---|---|
| 1 | Supabase project, schema + RLS, psycopg pool, JWT auth, dialect port off SQLite | Done |
| 2 | SQLite → Supabase data migration | Done |
| 3 | Frontend auth (supabase-js, guarded routes, bearer tokens) | Done |
| 4 | Single-host deploy (FastAPI serving built frontend) | Done |
| 5 | Per-user eBay OAuth (`ebay_connections`, encrypted tokens) | Done |
| 6 | Per-user sync replacing the workbook pipeline | Done |
| 7 | Retire the Drive workbook entirely | In progress — both paths still live |

The full current-vs-target design, schema, and SQLite→Postgres dialect mapping rules live in
`docs/SOFTWARE_PLAN.md`. It's maintained as a living design doc, not a historical record.

---

## 13. Talking points — likely questions and strong answers

**"What was the hardest problem?"**
The sold-search discovery (§8.4). The system's entire pricing basis was built on an API filter
that didn't exist and failed silently. Finding it required not trusting the response shape and
diffing it against a plain active search. The fix was a data-source swap plus a comment in the
code preventing the mistake from being reintroduced.

**"Tell me about a bug you caused and what you learned."**
The duplicated pricing logic in the frontend — two pages calling the same function with
different inputs, producing two different "suggested" prices for one listing. The lesson wasn't
"be more careful," it was structural: **business logic that must be consistent belongs in one
server-side place, computed once and stored, with the client only formatting it.** Same
reasoning applied to the self-exclusion feedback loop — both were "the same number computed in
two contexts" problems.

**"How does this scale?"**
Market research is per-card, not per-user, so the dominant API cost grows with the *catalog*,
not with users. Advisory locks make the jobs safe under multiple processes. The bottleneck is
eBay's application-level rate limit, which is shared across all users — that's a real limit and
I'd address it with a proper job queue and per-card TTL scheduling rather than a 6-hour sweep.

**"Why Excel at all?"**
Because the business owner actually uses it. It was the existing source of truth and replacing
it on day one would have meant a rewrite with no user. Instead the workbook became one of two
ingest paths into the same schema, and it gets retired when the replacement demonstrably
covers it.

**"Why Supabase over rolling your own?"**
Auth, Postgres, and RLS in one managed service — the pieces that are boring to build and
expensive to get wrong. The tradeoff: pgBouncer transaction mode means no prepared statements
(hence `prepare_threshold=None`), and JWT verification had to handle both their current ES256
and legacy HS256 schemes.

**"What would you do next / what's not done?"** (Be direct about these — see §14.)

---

## 14. Known gaps — answer these honestly if asked

Volunteering these reads as self-aware, not as weakness. Every one has a clear "what I'd do
about it."

1. **No test suite.** The single biggest gap. `suggested_price.py` is a pure function with rich
   intermediates — it is *designed* to be tested and has no tests. That's where I'd start:
   table-driven tests over the model, then the card matcher, then contract tests against
   recorded eBay responses.
2. **There are two committed typos in `dashboard/backend/services/ebay_oauth.py`** that would
   break the OAuth callback at runtime: `rows[0]["usfier_id"]` (should be `user_id`, line ~106)
   and stray characters inside the SQL string at lines ~161–162 (`e       refresh_token` and
   `scopes = EXCLUDED.scopes,ad`). Worth fixing before any demo — a live walkthrough of "connect
   your eBay account" would fail on it. Nothing else references those lines, so it's a
   three-character fix.
3. **Single-instance assumption.** `reconcile_stale_job_runs()` marks *all* running jobs as
   orphaned on startup, which is only correct with one replica. Scaling out needs a heartbeat
   or lease column instead.
4. **In-process scheduler.** A daemon thread in the API process couples job execution to request
   serving. Fine at this scale; the right answer at any larger one is a separate worker and a
   real queue.
5. **No cost basis.** There's no COGS column anywhere, so "never sell at a loss" is not
   actually computable — `MIN_NET_PROCEEDS` and `ASSUMED_SHIP_COST` are deliberate proxies. The
   code says so explicitly.
6. **`active_market_listings` is never pruned.** Reads filter to the last 14 days, but the table
   grows unbounded.
7. **`sold_listings` and the "Recent Sold Avg" naming are legacy** from the era of the fake sold
   search; the numbers now come from TCGdex with `sample_size=1`. The column names haven't
   caught up with the semantics.
8. **`CLAUDE.md` is slightly stale** — it lists Pricing and Promotions frontend pages that were
   removed in commit `9b1d0b2`. Current routes are Dashboard, Sold, Active, Listing Detail,
   Settings, Login.

---

## 15. Quick reference — key files

| File | Why it matters |
|---|---|
| `docs/SOFTWARE_PLAN.md` | Living design doc: current vs. target architecture, full schema, phase plan |
| `dashboard/backend/services/suggested_price.py` | The pricing model. Pure, heavily documented, the showpiece |
| `dashboard/backend/services/price_research.py` | Shared research orchestration, advisory locking, job lifecycle |
| `dashboard/backend/services/ebay_data.py` | Per-user OAuth sync — the workbook replacement |
| `dashboard/backend/routers/active.py` | Biggest router: listing reads, price revision, bulk apply, history |
| `src/ebaypricer/trading_api.py` | eBay Trading XML client + the Best Offer sequencing logic |
| `src/ebaypricer/cards.py` | Title → canonical card matching |
| `src/ebaypricer/browse_api.py` | Marketplace search + the "don't recreate the sold search" comment |
| `db/migrations/0001–0005` | Schema evolution, each with a rationale header |
| `dashboard/frontend/src/pages/ActiveListingsPage.tsx` | Bulk review-then-confirm reprice flow |

---

## 16. One-paragraph version for a resume bullet

> Built an end-to-end eBay seller-automation platform for a Pokémon card business: a Python
> data pipeline integrating six eBay APIs (Trading, Browse, Marketing, Finances, Fulfillment,
> OAuth) with a FastAPI backend and React 19/TypeScript dashboard. Designed a server-side
> pricing model that blends competitor comps, listing staleness, search rank, condition, and
> demand signals into a per-listing recommendation with explainable reasoning, then applies
> approved changes to live listings in bulk. Migrated the system from a single-user
> SQLite/Excel tool to a multi-tenant Supabase Postgres SaaS with per-user OAuth, Fernet-
> encrypted token storage, and row-level security — using Postgres advisory locks and a
> job-run audit table for safe concurrent background processing. Deployed on AWS ECS Fargate
> via a multi-stage Docker build.
