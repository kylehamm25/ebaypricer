-- EbayPrice: seller vetoes on suggested prices.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0019.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- One row per listing the seller thumbed-down, recording which direction was
-- vetoed ('up' = the suggestion raised the price, 'down' = it cut it) and what
-- the rejected suggestion was. services/price_research.py reads the whole table
-- into one map per run (like price_change_log for the cooldown) and
-- services/suggested_price.py turns an unexpired veto into a one-sided bound at
-- the current price: a downvoted increase can still cut, a downvoted decrease can
-- still rise - only the vetoed direction is held, for FEEDBACK_HOLD_DAYS.
--
-- One row per (user, listing): voting again replaces the veto (and restarts its
-- clock), deleting the row clears it. Expired rows are simply ignored past
-- FEEDBACK_HOLD_DAYS - volume is one row per vetoed listing, so no pruning.
-- ==============================================================

create table if not exists public.price_feedback (
    user_id         uuid not null references auth.users(id) on delete cascade,
    item_id         text not null,
    direction       text not null check (direction in ('up', 'down')),
    suggested_price numeric(10,2),
    voted_at        timestamptz not null default now(),
    primary key (user_id, item_id)
);

alter table public.price_feedback enable row level security;
-- User-owned, same shape as price_change_log. Backend writes via service_role,
-- which bypasses RLS; this policy is what lets a user read their own feedback.
create policy "price_feedback_owner_all" on public.price_feedback
    for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
