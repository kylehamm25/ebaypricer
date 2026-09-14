-- EbayPrice: keep a hand-corrected catalog match from being re-derived by the sync.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0012.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- `active_listings.card` is the catalog identity a listing prices against - it is
-- what browse_api searches for, what active_price_snapshots is keyed on, and what
-- the card art resolves from. It is produced by fuzzy-matching the eBay title in
-- cards.enrich_rows, which is right most of the time and wrong in the ways fuzzy
-- matching is always wrong: the correct card in the wrong set, the base print of a
-- stamped promo, a Trainer whose name collides with a Pokemon.
--
-- A wrong match is not cosmetic. It prices the listing against a different card.
--
-- Correcting it by hand used to be pointless because every sync upserts
-- `card = EXCLUDED.card` and put the fuzzy guess straight back. This flag is what
-- makes a correction stick: both sync paths write
--     card = CASE WHEN active_listings.card_locked THEN active_listings.card
--                 ELSE EXCLUDED.card END
-- so a locked row keeps the value a person chose and an unlocked one keeps
-- following the matcher. Clearing the flag hands the row back to the matcher on
-- the next sync.
--
-- Deliberately a lock on the existing column rather than a second `card_override`
-- column: everything that reads a listing's card - price_research, the comp
-- filter, the art lookup, routers/lots - reads `card`, and a parallel column would
-- mean auditing every one of those read sites to coalesce, with a silent wrong
-- price wherever one was missed.
--
-- services/upsert_rules.py degrades if this hasn't been run: it checks for the
-- column once per sync and falls back to the plain overwrite, so an un-migrated
-- install syncs exactly as it did before.
-- ==============================================================

alter table public.active_listings
    add column if not exists card_locked boolean not null default false;
