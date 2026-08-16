---
name: ebay-api-rate-limits
description: Rate-limit, retry, timeout, and caching behavior for the eBay Browse/Trading/Marketing APIs and TCGdex as used in this repo. Load before writing or changing any code that calls an external API, adds a research loop, iterates over cards or listings, or touches retry/backoff/caching.
---

# eBay + TCGdex rate limits and backoff

Throttling here is not theoretical — the research loop iterates every unique card
across every user, so a naive change turns one extra call per card into hundreds
of extra calls per run.

## The single most important rule

**Go through the existing client functions.** They carry the retry and backoff
behavior. A direct `requests.get` against an eBay endpoint bypasses all of it.

| Use | Not |
|---|---|
| `browse_api.search_active_listings` | `requests.get(".../item_summary/search")` |
| `trading_api.fetch_*` / `revise_*` | a hand-rolled `ws/api.dll` POST |
| `marketing_api.*` | a direct `sell/marketing/v1` call |
| `cards.lookup_market_price` | a direct TCGdex call |

## Encoded behavior, per API

### Browse API (`browse_api.py`)
- `timeout=15`
- **429 → sleep 60s, retry, max `MAX_RATE_LIMIT_RETRIES` (3)**, then raise.
  Implemented as recursion carrying `_retries`; preserve that if you refactor.
- `LISTING_LIMIT = 50`, `MAX_QUERY_WORDS = 5` — queries are truncated to 5 words,
  which is also why `_candidate_queries` generates a few short variants instead of
  one long one.
- No other status code is retried. A 5xx propagates.

### Trading API (`trading_api.py`)
- `timeout=30` for list fetches, `timeout=15` for `GetItem` and revisions.
- Pagination at `EntriesPerPage=200`, looping to `TotalNumberOfPages`. Large
  catalogs mean multiple calls per refresh — do not call these per-item in a loop.
- No 429 handling. Failures surface via the `Ack` field, not the HTTP status:
  anything outside `Success` / `Warning` is an error.
- `resolve_condition` avoids a `GetItem` call entirely when the title already
  states the condition. Keep that short-circuit — it is one saved call per listing.

### Marketing API (`marketing_api.py`)
- `timeout=15`, `timeout=30` for bulk.
- Pagination `limit=200`; `bulk_update_bids` takes **up to 500 listings per call**
  — batch, never loop per listing.
- 401 and 403 raise `MarketingApiError` rather than exiting. 403 specifically
  means the account is not eligible for Promoted Listings; that is a normal
  per-user outcome, not a job failure, and must not abort a batch across users.

### TCGdex (`cards.py`)
- `timeout=10` for cards, `timeout=30` for the set map.
- Results are cached in `PRICING_CACHE`, including **negative caching** — a 404
  stores `None` so a missing card is not re-fetched forever.
- The set map is fetched once and persisted to `TCGDEX_SET_MAP`.

## Loop discipline

These are the patterns that keep a full-catalog run inside budget. Preserve them.

**Daily snapshot cache.** `research_card_sold` / `research_card_active` return
today's existing snapshot unless `force=True`, and `run_shared_price_research`
skips the whole run when every card is already done today. Never pass `force=True`
from inside a loop or a request handler — it exists for algorithm changes and
single-card refresh.

**Per-query memoization within a run.** `research_card_positions` caches search
results per query string, because items sharing a card share candidate queries.

**Inter-call sleep.** `research_card_active` sleeps 0.5s per card. Keep a delay on
any new per-card API loop.

**Wall-clock budget.** `MAX_RUN_SECONDS` (45 min) bounds a research run and
remaining cards roll to the next run. This exists because the run holds a Postgres
advisory lock — an unbounded slow tail would block every future manual and
scheduled run indefinitely. Any new long batch job needs the same treatment.

**Advisory locks.** A thread lock plus a Postgres advisory lock guarantees one
runner per job across processes. Keys in use: `727001` pipeline, `727002`
research, `727003`/`727004` stage sold/active. **Pick a new key for a new job.**

**Never research in a request handler.** `refresh_card` is the one synchronous
per-card path (it deliberately bypasses the batch lock so a single-card refresh
does not queue behind a full run). Everything else runs on a background thread.

## Quotas

eBay enforces per-application daily call limits that vary by API and account
standing. **This repo does not track or hardcode them** — the only defense in code
is the 429 handler above. So: if you are asked what the quota is, check eBay's
developer console rather than guessing, and when adding a call path, reason about
calls-per-card × cards-per-run rather than about a number.

Rough per-run shape today: one Browse search per card for active comps, plus up to
three more for search-position candidate queries (memoized), plus one TCGdex
lookup per card (cached, often free). Adding "just one more call per card"
multiplies by the whole catalog.
