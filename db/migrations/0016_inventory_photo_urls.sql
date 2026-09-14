-- EbayPrice: web-hosted photos of a card in the unlisted pile, for eBay's prefill
-- listing template.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0015.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- eBay's prefill flow takes a photo URL per item and reads the FIRST one to work out
-- what the item is. Nothing else in this app has anywhere to put one: `card_image_url`
-- on the API response is catalog art resolved from card_query at read time, which is a
-- picture of the printing rather than a photo of the card in hand - it cannot carry a
-- condition, and eBay's terms make the seller warrant rights to every URL supplied.
-- So the photos a listing will actually use have to be stored, and this is where.
--
-- One text column, not a child table. The format is eBay's: up to 24 https:// links
-- separated by a pipe, first one first, which is exactly how the template wants the
-- cell and exactly how it comes back out. A join table would buy ordering guarantees
-- the pipe string already has, and cost a query per page load.
--
-- Nullable, like everything else here. A row with no photos is normal - most of the
-- pile has never been photographed - and the prefill export simply leaves the cell
-- empty, which the template allows (Title alone satisfies Set A).
-- ==============================================================

alter table public.inventory
    add column if not exists photo_urls text;
