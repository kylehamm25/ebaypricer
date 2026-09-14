-- EbayPrice: an optional seller-set floor for the inventory listing CSV's starting price.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0017.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- services/listing_csv.py already floors a new listing's price at net_floor() - the
-- least that clears eBay fees plus postage. That is a break-even number, not a seller
-- preference: some sellers don't want to open a listing under, say, $2 even when the
-- comps and the fee floor would allow it. min_price is that second, optional floor -
-- unlike the four fields in 0015 it is never required, so listing_settings.missing()
-- deliberately leaves it out and a CSV can still be built with none set.
--
-- Null means "no minimum", not zero - a seller who has never opened Settings gets the
-- fee floor alone, the same behaviour as before this migration existed.
--
-- Separate migration rather than an edit to 0015 because 0015 has already been
-- applied; `create table if not exists` would not have added a column to it.
-- services/listing_settings.py degrades if this hasn't been run: the four required
-- fields still read and save, and only a supplied min_price is refused (mirroring how
-- 0012's manual_value and 0016's photo_urls behave on the inventory table).
-- ==============================================================

alter table public.listing_defaults
    add column if not exists min_price numeric(10,2);
