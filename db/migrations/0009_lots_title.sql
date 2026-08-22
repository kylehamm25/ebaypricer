-- EbayPrice: a human-readable name for a buying lot.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0008.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- The SKU (L0030, L0041, ...) is the lot's identity and is what ties a card back
-- to the batch it came from, but it says nothing about what the batch actually
-- was. This is the label for that - "Estate collection, 2500 bulk", "Vintage WOTC
-- binder" - shown as the lot's main line on the Lots page with the SKU beneath.
--
-- Separate migration rather than an edit to 0008 because 0008 has already been
-- applied; `create table if not exists` would not have added the column to an
-- existing table. routers/lots.py degrades if this hasn't been run yet: costs
-- still save, and only a supplied title is refused.
-- ==============================================================

alter table public.lots
    add column if not exists title text;
