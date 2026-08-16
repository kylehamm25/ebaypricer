-- Average competitor shipping cost per card, so the suggested-price model can
-- compare total landed price (item + shipping) instead of item price alone.
-- See dashboard/backend/services/price_research.py::research_card_active and
-- suggested_price.py::compute_suggested_price's shipping-adjusted positioning.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0006.

alter table public.active_price_snapshots
    add column if not exists avg_shipping numeric(10,2);
