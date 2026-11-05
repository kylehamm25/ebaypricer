-- EbayPrice: the back photo of a scanned card, stored alongside its import.
-- Paste into Supabase SQL editor and run once, after 0021. Idempotent.
--
-- A scan used to be one photo. A card is now photographed front and back as a pair,
-- and the back is kept on the same import so confirming copies both into
-- inventory.photo_urls in order (front first, which is the photo eBay reads to
-- identify the item). Recognition still runs on the front only.
--
-- Nullable and additive: an install that hasn't run this still scans fronts, and a
-- scan that supplies a back is refused with the migration name rather than silently
-- dropping the photo.

alter table public.inventory_imports
    add column if not exists back_image_url text;
