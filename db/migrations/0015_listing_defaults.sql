-- EbayPrice: the seller's standing listing settings - item location and the eBay
-- business policy names the bulk-listing CSV attaches.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0014.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- These four values are the only thing POST /inventory/listing-csv needs that an
-- inventory row cannot know, and they are the same on every export forever: the ZIP
-- you ship from, and the exact Seller Hub names of your shipping, payment and return
-- policies. Typing them per export was the whole friction; they belong on Settings.
--
-- A row per user rather than a browser preference. Everything else the pages remember
-- locally - the seed location, the grid/table toggle, the valuation draft - is a
-- convenience whose loss costs a keystroke. These are account facts: a name that
-- doesn't match a real Seller Hub policy is the commonest reason a File Exchange
-- upload comes back rejected, so getting them right once should hold on every machine
-- the user signs in from, not just the browser they happened to type them in.
--
-- One row per user (user_id is the primary key), so reads never have to pick a
-- "current" row and writes are a plain upsert.
--
-- Everything is nullable and there are no defaults beyond the shipping profile:
-- an unconfigured user is a real state, and the CSV endpoint refuses with a message
-- pointing at Settings rather than inventing a location or a policy name. Guessing
-- here does not produce a slightly-wrong listing, it produces a rejected upload.
--
-- shipping_profile carries a default because there IS a right answer for it -
-- SHIPPING_PRICE_MAP in ebaypricer/listing_economics.py has to know the name or the
-- CSV's price floor assumes postage is free, and 'Free ebay standard' is both the
-- extension's default and a key in that map.
-- ==============================================================

create table if not exists public.listing_defaults (
    user_id          uuid primary key references auth.users(id) on delete cascade,
    item_location    text,                                  -- ZIP or city eBay shows buyers
    shipping_profile text default 'Free ebay standard',     -- must stay a SHIPPING_PRICE_MAP key
    payment_profile  text,                                  -- exact Seller Hub policy name
    return_profile   text,                                  -- exact Seller Hub policy name
    updated_at       timestamptz not null default now()
);

alter table public.listing_defaults enable row level security;
-- User-owned, same shape as inventory and lots. The backend writes via service_role,
-- which bypasses RLS; this policy is what lets a user read their own row.
create policy "listing_defaults_owner_all" on public.listing_defaults
    for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
