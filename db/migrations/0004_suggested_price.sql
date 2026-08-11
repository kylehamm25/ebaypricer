-- EbayPrice: stored suggested price + 25th-percentile comp anchor.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0003.
-- Columns are added IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- Suggested price, computed server-side by
-- dashboard/backend/services/suggested_price.py and written during the
-- shared price-research job. Replaces the old client-side calculation, which
-- lived in two places and produced two different numbers for the same listing.
--
-- suggested_price_basis holds the model's intermediates (anchors, staleness /
-- rank weights, condition multiplier, pre-guardrail target, which clamps
-- bound it). jsonb rather than discrete columns because the shape will change
-- as the model is tuned, and it is only ever read for display - never filtered
-- on. Same pattern as job_runs.detail.
--
-- NOTE: deliberately NOT added to the Excel "Active Listings" sheet or to
-- excel_sync._ACTIVE_COLUMNS / ebay_data._ACTIVE_MAP. Those syncs write every
-- column present in their column maps, so adding it there would let a workbook
-- round-trip clobber the computed value (which is exactly what happens to
-- search_position today).
-- ==============================================================

alter table public.active_listings
    add column if not exists suggested_price       numeric(10,2),
    add column if not exists suggested_price_at    timestamptz,
    add column if not exists suggested_price_basis jsonb;

-- ==============================================================
-- 25th-percentile competitor price - the "competitive floor" anchor the
-- staleness ramp pulls toward. Preferred over min_price, which is a single
-- listing surviving a 2-sigma filter that only engages at n >= 4, so one
-- junk/wrong-print listing could otherwise set the floor for the whole card.
-- ==============================================================

alter table public.active_price_snapshots
    add column if not exists p25_price numeric(12,2);
