-- EbayPrice: keep eBay's blank prefill template on file, so the Inventory page can
-- fill it without being handed it again every time.
-- Paste into Supabase SQL editor (Dashboard > SQL Editor) and run once, after 0016.
-- Created IF NOT EXISTS so the script is idempotent.

-- ==============================================================
-- eBay's prefill flow needs its own workbook filled in - "do not change any formatting
-- in the file" - so the app cannot generate one, it has to edit theirs. That made the
-- template an upload on every export, which is the same friction the policy names had
-- in 0015: one unchanging thing, re-entered per use.
--
-- So it is stored, beside the settings it belongs with. The template changes when eBay
-- revises it, which is rarely, and replacing it is one upload on the Settings page.
--
-- bytea rather than a storage bucket: the file is tens of KB, this project has no
-- bucket wired up, and the bytes are useless without the row they hang off. Note it is
-- deliberately NOT in `listing_settings.FIELDS` - that SELECT runs on the listing-CSV
-- path, which has no use for the workbook and should not drag it through the pool.
--
-- The name and timestamp are stored so Settings can say WHICH file is on record and
-- when. A stored blob nobody can identify is worse than no blob: the one question the
-- page has to answer is "is this still the current template?".
-- ==============================================================

alter table public.listing_defaults
    add column if not exists prefill_template      bytea,
    add column if not exists prefill_template_name text,
    add column if not exists prefill_template_at   timestamptz;
