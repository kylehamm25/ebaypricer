-- Adds competitor shipping cost to active_market_listings, sourced from the Browse
-- API's shippingOptions (see ebaypricer.browse_api.parse_active_item). Paste into
-- Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0005.

alter table public.active_market_listings
    add column if not exists shipping_cost numeric(10,2);

alter table public.active_market_listings
    add column if not exists shipping_cost_type text;
