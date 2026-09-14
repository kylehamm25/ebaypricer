-- EbayPrice: a hand-stated value for inventory rows the market can't be asked about.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0011.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- Sealed product, bulk priced as one line, a card already appraised - none of
-- these have a catalog card, so `card_query` is null and there are no comps to
-- average. Before this they simply had no value at all and sat outside the
-- Est. Value total, which understated the pile by however much of it was sealed.
--
-- Per UNIT, matching `cost`, so quantity multiplies it the same way.
--
-- A value here WINS over comps for that row. That is what makes it useful on a
-- catalog card too: when the comp pool is visibly wrong for a printing you own,
-- stating the number outright is better than living with a bad average.
-- routers/inventory.py reports such a row as value_status 'manual' so the page can
-- say where the number came from rather than passing it off as market data.
--
-- The condition multiplier is deliberately NOT applied to it - the same rule
-- /valuation/manual follows, and for the same reason: a comp average is a
-- mixed-condition figure that has to be scaled to the card in hand, but a price
-- the seller typed is already the value of the actual card, and scaling it again
-- would quietly reduce a number they stated outright.
--
-- Separate migration rather than an edit to 0011 because 0011 has already been
-- applied; `create table if not exists` would not have added a column to it.
-- routers/inventory.py degrades if this hasn't been run: rows still read and save,
-- and only a supplied manual value is refused.
-- ==============================================================

alter table public.inventory
    add column if not exists manual_value numeric(10,2);
