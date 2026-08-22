-- EbayPrice: per-card record of how much of a comp pool was usable.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0009.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- eBay's Browse API matches on words, not on card identity, so a search for a card
-- returns graded slabs, multi-card lots, print-error one-offs, foreign-market prints
-- and wrong prints alongside the ordinary copies we want to price against. Measured
-- before comp_filter existed, the pool for "Charmander 46 Base" ran $0.99-$1500 on a
-- card listed at $5.24, and "Charizard ex 105 FireRed & LeafGreen" ran $13-$15,000.
--
-- src/ebaypricer/comp_filter.py now drops those. This column records what it dropped
-- and why, per card per day:
--
--   {"in": 30, "kept": 24, "dropped": 6, "soft_restored": false, "identified": true,
--    "reasons": {"graded": 2, "multi_card": 1, "reverse_mismatch": 3}}
--
-- Why persist it rather than only log it: a suggestion computed off a badly polluted
-- pool and one computed off a clean pool look identical in active_listings - a number.
-- Without this, pool contamination is only ever visible as a suggested price that
-- happens to look wrong, and there is no way to tell whether a filter rule change
-- helped or hurt. "soft_restored": true specifically flags a pool that was too thin
-- after filtering, so its anchors are known to include comps we would rather have
-- dropped.
--
-- jsonb rather than columns per reason so a new filter rule doesn't need a migration.
-- Nullable: rows written before this migration, and any run where the filter is
-- skipped, simply carry NULL.
-- ==============================================================

alter table public.active_price_snapshots
    add column if not exists pool_quality jsonb;

-- active_price_snapshots is shared marketplace data (not user-owned), same as the rest
-- of this table - no RLS policy change is needed.
