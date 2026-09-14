-- EbayPrice: take a card out of the unlisted pile once it has been listed.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0013.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- Read 0011's note first: this table has deliberately never carried a "listed"
-- flag, because two tables both claiming to know whether a card is listed is how
-- they end up disagreeing. That still holds, and this column does NOT break it.
--
-- `archived_at` records that a row has LEFT THE PILE - nothing more. It is a
-- timestamp of when you were done with it, not an assertion about eBay. Nothing
-- reads it as "this is listed", nothing reconciles it against active_listings, and
-- active_listings remains the only thing that knows what is actually on eBay.
--
-- The reason it exists rather than deleting the row: deleting throws away the
-- condition, the location, the lot and the price you had researched, so if the
-- listing ends or you were wrong about having listed it, there is nothing to
-- restore. Archiving keeps the work and takes it out of the way.
--
-- Consequences, all of them the point:
--   * GET /inventory hides archived rows by default; ?archived=archived|all shows them.
--   * The Est. Value / Cards / Cost totals count only what is still in the pile.
--   * A lot's unlisted_items / unlisted_value ignore archived rows, so a card does
--     not sit in a lot's "unlisted" column after it has been listed AND get counted
--     again in that lot's listed_value from active_listings. That double count is
--     precisely the disagreement 0011 was guarding against.
--
-- Partial index because every ordinary read filters to the live pile.
-- ==============================================================

alter table public.inventory
    add column if not exists archived_at timestamptz;

create index if not exists idx_inventory_user_live
    on public.inventory (user_id) where archived_at is null;
