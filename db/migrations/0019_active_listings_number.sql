-- EbayPrice: a sortable card number for active listings.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0018.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- `active_listings.card` is a formatted catalog identity string ("Charizard 4 Base
-- Set"), not a set of columns - the number is embedded in it, not queryable, and so
-- can't be an ORDER BY key on its own. This column stores just that one piece,
-- derived from `card` via ebaypricer.cards.card_number() (a thin wrapper around
-- card_identity()) - purely so the Active Listings page can sort by it in SQL, the
-- same way it already sorts by Price or Days Listed.
--
-- Populated by both sync paths (services/excel_sync.py, services/ebay_data.py)
-- whenever `card` is written, and by the manual card-correction endpoint
-- (PUT /active/item/{id}/card) when a match is corrected by hand. It rides along
-- with `card` under the same card_locked protection (services/upsert_rules.py's
-- LOCKED_COLUMNS) - a locked row's number stays whatever it was derived from the
-- locked card, never silently drifting out of step with it.
--
-- Null, not empty string, when nothing parses (a free-text search, sealed/bulk with
-- no catalog match) - the same "no value" convention every other column here uses,
-- and what lets NULLS LAST push those rows to the end instead of grouping them
-- under a false empty-string "number".
--
-- Both sync paths degrade if this hasn't been run: card_locked's has_column() check
-- already gates whether the lock CASE is even written per column, so an un-migrated
-- database simply never gets `number` in its upsert column list. The manual
-- correction endpoint checks explicitly (existing_columns) and skips setting it
-- rather than raising.
-- ==============================================================

alter table public.active_listings
    add column if not exists number text;
