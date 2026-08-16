-- EbayPrice: purchase cost for each buying lot, keyed by the SKU already stamped
-- on every listing and order.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0007.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- What a "lot" is here: a batch of cards bought together (a collection, a
-- bulk box, an estate buy), tracked by the SKU the seller already puts on
-- every listing from that batch - L0030, L0041, and so on. PULL (cards pulled
-- from packs personally, nothing was paid per card), NONTCG, and rows with no
-- SKU at all are NOT purchased lots; routers/lots.py excludes them, and their
-- sales stay visible on the Sold Orders page instead.
--
-- This table holds ONLY the facts that cannot be derived: what was paid, when,
-- and from whom. Everything else on the Lots page - items still listed, current
-- listed value, units sold, net proceeds, profit - is aggregated live from
-- active_listings and sold_orders by routers/lots.py. That is deliberate: a lot
-- shows up on the page as soon as its SKU appears in the data, with or without a
-- row here, so there is no "create the lot first" step to forget.
--
-- Keyed by (user_id, sku) rather than a surrogate id because the SKU IS the lot
-- identity in this business - it is what ties a card back to the batch it came
-- from, and it is already stamped on the eBay listing.
-- ==============================================================

create table if not exists public.lots (
    user_id      uuid not null references auth.users(id) on delete cascade,
    sku          text not null,
    cost         numeric(10,2),   -- total paid for the whole lot, not per card
    purchased_at date,
    source       text,            -- where it was bought (seller, show, shop)
    notes        text,
    updated_at   timestamptz not null default now(),
    primary key (user_id, sku)
);

alter table public.lots enable row level security;
-- User-owned, same shape as price_change_log. Backend writes via service_role,
-- which bypasses RLS; this policy is what lets a user read their own lots.
create policy "lots_owner_all" on public.lots
    for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
