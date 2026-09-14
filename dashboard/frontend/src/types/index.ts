export interface DashboardKpis {
  month: string
  available_months: string[]
  sold_items: number
  revenue: number
  shipping: number
  fees: number
  /** Real per-order net for the month (gross - fees - debits - postage), the same
   *  figure the Sold page reports. Never revenue minus fees. */
  earnings: number
  active_listings: number
  trends: { date: string; count: number; revenue: number }[]
  top_items: { title: string; count: number; avg_price: number; revenue: number }[]
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface SoldSummary {
  total_items: number
  total_revenue: number
  total_shipping: number
  total_fees: number
  /** Real per-order net from the Finances API (gross - fees - debits - postage), not
   *  revenue minus fees. Shipping revenue is inside the gross, so the label we bought
   *  is taken back out. */
  total_earnings: number
  /** Orders whose fee data hasn't posted yet, so they contribute 0 to total_earnings. */
  orders_missing_net: number
  avg_price: number
}

export interface SoldTrend {
  date: string
  count: number
  revenue: number
}

export interface ActiveSummary {
  total_listings: number
  total_value: number
  avg_days_listed: number
  avg_watchers: number
  avg_price: number
}

export interface ConditionDist {
  condition: string
  count: number
}

export interface DaysBucket {
  bucket: string
  count: number
}

export interface ValueBucket {
  bucket: string
  count: number
  value: number
  count_pct: number
  value_pct: number
}

export interface ValueBucketResponse {
  buckets: ValueBucket[]
  total_count: number
  total_value: number
}

export interface PriceChangeEntry extends Record<string, unknown> {
  item_id: string
  old_price: number | null
  new_price: number
  source: string
  changed_at: string
  title: string | null
  card: string | null
  current_price: number | null
}

export interface PriceChangesResponse {
  days: number
  cooldown_days: number
  changes: PriceChangeEntry[]
}

export interface PriceComparison {
  card_query: string
  /** Mean competitor ITEM price, shipping excluded. */
  active_avg: number | null
  /** Mean shipping charged across the same comp pool. Null means no comp reported
   *  one - not that they ship free. */
  avg_shipping: number | null
  /** active_avg + avg_shipping: what a buyer actually pays a competitor. Null
   *  whenever avg_shipping is, so it is never a disguised item-only figure. */
  active_avg_total: number | null
  active_min: number | null
  active_sample: number | null
}

export interface ActiveSnapshot {
  card_query: string
  snapshot_date: string
  sample_size: number | null
  avg_price: number | null
  min_price: number | null
  max_price: number | null
}

export interface ActiveMarketListing extends Record<string, unknown> {
  item_id?: string
  card_query?: string
  title: string
  price: number | null
  currency?: string | null
  condition: string | null
  listing_type: string | null
  url?: string | null
  shipping_cost?: number | null
  shipping_cost_type?: string | null
  pulled_at?: string | null
}

export interface CardPriceDetail {
  card_query: string
  matched_query?: string | null
  active_snapshots: ActiveSnapshot[]
  recent_active: ActiveMarketListing[]
}

export interface PositionHistoryPoint {
  snapshot_date: string
  position: number
  search_size: number
}

/** Why the model landed on a given suggested price. Written by
 *  dashboard/backend/services/suggested_price.py; read-only for display. */
export interface SuggestedPriceBasis {
  v: number
  status: 'ok' | 'cooldown' | 'thin_comps' | 'no_comps' | 'excluded' | 'comp_mismatch'
  matched_keyword?: string
  /** status 'cooldown': this listing was repriced recently and is not re-suggested
   *  until cooldown_days have passed. See REPRICE_COOLDOWN_DAYS in suggested_price.py. */
  days_since_price_change?: number
  cooldown_days?: number
  anchor_avg?: number
  anchor_floor?: number
  /** status 'comp_mismatch': anchor_avg / current_price, when that ratio exceeded
   *  MAX_ANCHOR_RATIO in either direction and the comp pool was judged to be a
   *  different product. */
  anchor_ratio?: number
  max_anchor_ratio?: number
  current_price?: number
  comps?: number
  days_listed?: number | null
  rank?: number | null
  w_days?: number
  w_rank?: number | null
  w?: number
  condition?: string
  condition_mult?: number
  /** What we charge the buyer for shipping, and the comp pool's average - the gap
   *  between them shifts the target so it's positioned on total landed price
   *  (item + shipping) rather than item price alone. */
  shipping_charge?: number | null
  comp_avg_shipping?: number | null
  shipping_adjustment?: number
  /** Buyer-paid shipping matches an eBay Standard Envelope rate, so the suggestion
   *  is not allowed to raise the price past ese_max_price (ESE only carries items
   *  declared at $20 or under). Shows up in `clamps` as 'ese_max_price' when it bound. */
  ese_shipping?: boolean
  ese_max_price?: number
  watchers?: number | null
  watcher_pull?: number
  /** The model's true target before guardrails clamped it. */
  pre_guardrail?: number
  clamps?: string[]
  flags?: string[]
}

export interface ActiveListing extends Record<string, unknown> {
  'Item ID': string
  Title: string
  Card: string | null
  Condition: string | null
  SKU: string | null
  Price: number | string | null
  'Shipping Charge': number | string | null
  'Ad Rate': string | null
  Watchers: number | string | null
  'Days Listed': number | string | null
  'Start Date': string | null
  Quantity: number | string | null
  'Estimated Fees': number | string | null
  'Estimated Net': number | string | null
  'Last Checked': string | null
  'Active Avg (Top 5)': number | string | null
  'Price Accuracy': number | string | null
  'Search Position': number | string | null
  'Suggested Price': number | string | null
  'Suggested Price At': string | null
  /** True when the catalog match was set by hand. The sync then leaves `Card`
   *  alone instead of re-deriving it from the title (migration 0013). Absent on
   *  the list endpoint - only the detail endpoint reads it. */
  'Card Locked'?: boolean
  'Suggested Price Basis': SuggestedPriceBasis | null
  /** Pokemon species pixel sprite, matched off the listing title. */
  sprite_url?: string
  /** Actual card art, resolved from the card_query. Null when the listing never matched a catalog card. */
  card_image_url?: string | null
}

export interface PipelineStatus {
  state: 'idle' | 'running'
  pid: number | null
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
}

export interface EbayStatus {
  connected: boolean
  ebay_user_id: string | null
  scopes: string | null
  token_expires_at: string | null
  last_synced_at: string | null
  sync_status: string | null
}

/** A buying lot, keyed by the SKU stamped on its listings and orders. Only `cost`,
 *  `purchased_at`, `source` and `notes` are stored (table `lots`); every other
 *  field is aggregated live from active_listings + sold_orders by routers/lots.py.
 *  The profit fields are null until a cost is entered - never 0, which would read
 *  as "broke even". */
export interface Lot extends Record<string, unknown> {
  sku: string
  /** Human-readable name for the lot ("Estate collection, 2500 bulk"). Undefined
   *  rather than null when migration 0009 hasn't been run. */
  title?: string | null
  cost: number | null
  purchased_at: string | null
  source: string | null
  notes: string | null
  active_items: number
  listed_value: number
  /** Bought under this lot, catalogued, not listed yet (the Inventory page).
   *  Counted apart from active_items - nobody can buy these. */
  unlisted_items: number
  unlisted_entries: number
  unlisted_value: number
  /** Unlisted rows with no price to contribute, so unlisted_value isn't read as
   *  covering all of them. */
  unlisted_unvalued: number
  sold_items: number
  sold_gross: number
  sold_net: number
  /** Sold rows whose fee data hasn't arrived from the Finances API yet, so they
   *  contribute nothing to sold_net. Shown as a caveat, not silently counted as 0. */
  sold_missing_net: number
  total_items: number
  first_sale: string | null
  last_sale: string | null
  realized_profit: number | null
  projected_profit: number | null
  roi_pct: number | null
  recouped_pct: number | null
}

export interface LotTotals {
  cost: number
  sold_net: number
  listed_value: number
  unlisted_value: number
  unlisted_items: number
  realized_profit: number
  /** Sold net + listed value + unlisted value − cost. Optimistic on two counts:
   *  no fees are taken off the unsold half, and the unlisted part isn't even on
   *  eBay yet. Unpriced rows contribute nothing rather than being guessed at. */
  projected_profit: number
  tracked_lots: number
  untracked_lots: number
}

/** One choice in a lot-SKU picker: the buying lots from `GET /lots` merged with
 *  whatever SKUs inventory rows already carry, so a card can be assigned to a lot
 *  that has no inventory against it yet. */
export interface LotOption {
  sku: string
  title?: string | null
}

export interface LotsResponse {
  lots: Lot[]
  totals: LotTotals
  /** False until db/migrations/0008_lots.sql has been run; costs can't be saved. */
  cost_tracking_enabled: boolean
}

/** A sold line on the lot detail page. `line_net` is this line's allocated share
 *  of its order's net (see routers/lots.py), not the order-level figure - null
 *  while the Finances API hasn't reported the order's fees yet. */
export interface LotSoldRow extends Record<string, unknown> {
  order_id: string
  item_id: string
  item_title: string | null
  card: string | null
  sale_date: string | null
  quantity: number
  item_price: number | null
  line_gross: number | null
  line_net: number | null
  card_image_url?: string | null
  sprite_url?: string
}

/** A live listing on the lot detail page - the same rows counted in the lot's
 *  active_items / listed_value. */
export interface LotActiveRow extends Record<string, unknown> {
  item_id: string
  title: string | null
  card: string | null
  condition: string | null
  price: number | null
  shipping_charge: number | null
  quantity: number
  days_listed: number | null
  watchers: number | null
  start_date: string | null
  estimated_net: number | null
  suggested_price: number | null
  card_image_url?: string | null
  sprite_url?: string
}

/** One unlisted row behind a lot, valued exactly as the Inventory page values it. */
export interface LotUnlistedRow extends Record<string, unknown> {
  id: number
  name: string
  card_query: string | null
  condition: string | null
  quantity: number
  location: string | null
  cost: number | null
  unit_value: number | null
  total_value: number | null
  value_status: 'ok' | 'manual' | 'unresearched' | 'no_card'
  card_image_url?: string | null
  sprite_url: string | null
}

export interface LotDetailResponse {
  lot: Lot
  sold: LotSoldRow[]
  active: LotActiveRow[]
  unlisted: LotUnlistedRow[]
  cost_tracking_enabled: boolean
}

export interface CardHit {
  card_query: string
  name: string
  set_name: string
  number: string
  rarity: string
  set_series: string
  /** Derived from set_id + number, not stored - may 404 for the odd set, so render defensively. */
  image_url: string | null
}

export interface CardValue {
  card_query: string
  active_avg: number | null
  active_p25: number | null
  active_min: number | null
  active_max: number | null
  comps: number | null
  avg_shipping: number | null
  /** What comp_filter dropped and why. Null means this snapshot predates comp filtering. */
  pool_quality: { in: number; kept: number; dropped: number; reasons: Record<string, number>; soft_restored: boolean; identified: boolean } | null
  snapshot_date: string | null
  market_price: number | null
  /** eBay search that produced these comps, for eyeballing the pool. Null for manual rows. */
  search_url: string | null
  /** Pokemon species sprite parsed from the query text. Used for custom searches, which
   *  have no card art. Falls back to Pikachu when nothing parses. */
  sprite_url: string | null
  condition: string | null
  condition_mult: number
  condition_known: boolean
  adjusted_value: number | null
  estimated_fees: number | null
  estimated_net: number | null
  /** 'manual' = priced by hand, no comps and no condition multiplier applied. */
  status: 'ok' | 'no_comps' | 'not_found' | 'manual'
}

export interface RateLimit {
  name: string
  used: number
  limit: number
  remaining: number
  pct: number
  reset: string | null
}

export interface RateLimitsResponse {
  limits: RateLimit[]
  cached: boolean
}

export interface InventoryItem {
  id: number
  name: string
  /** Catalog identity, when the row is a catalog card. Null for sealed, bulk and
   *  anything typed free-hand - those rows never get a value estimate. */
  card_query: string | null
  set_name: string | null
  number: string | null
  condition: string | null
  quantity: number
  location: string | null
  sku: string | null
  /** Per unit, not for the whole row. */
  cost: number | null
  total_cost: number | null
  /** A value stated by hand, per unit. Wins over comps and is NOT scaled by the
   *  condition multiplier - a price you typed is already the value of the card in
   *  hand. Null when the row is priced from comps or not priced at all. */
  manual_value: number | null
  /** Web-hosted photos of this card: up to 24 https:// links separated by a pipe,
   *  first one first — eBay's own format, and the order matters because its prefill
   *  flow reads the first link to work out what the item is. Null before migration
   *  0016 and for anything never photographed. NOT the same as `card_image_url`,
   *  which is catalog art of the printing rather than a photo of this card. */
  photo_urls: string | null
  notes: string | null
  created_at: string | null
  /** When this row left the pile — you pressed Archive after listing the card.
   *  Null while it is still in the pile. NOT a claim that the card is listed on
   *  eBay: active_listings remains the only thing that knows that. */
  archived_at: string | null
  /** Real card art, resolved from card_query server-side. Null for rows with no
   *  catalog card, and for a card_query the catalog can no longer resolve. */
  card_image_url: string | null
  /** The eBay search the comps came from, openable so the pool can be eyeballed.
   *  Null only for a row with no card_query - there is no search behind those. */
  search_url: string | null
  /** Cached comp average x the condition multiplier. Never a suggested price, and
   *  never triggers an eBay call - see routers/inventory.py. */
  unit_value: number | null
  total_value: number | null
  /** 'ok' = from comps; 'manual' = the stated price above; 'unresearched' = a
   *  catalog card no run has priced yet; 'no_card' = nothing to price. */
  value_status: 'ok' | 'manual' | 'unresearched' | 'no_card'
  value_date: string | null
  comps: number | null
  condition_known: boolean
  /** False means the snapshot predates comp filtering, so it may average graded
   *  slabs and multi-card lots. Null when there is no value at all. */
  pool_filtered: boolean | null
}

export interface InventoryResponse {
  items: InventoryItem[]
  totals: {
    entries: number
    units: number
    value: number
    /** Entries the value figure covers - the rest have no cached comps. */
    valued_entries: number
    cost: number
    costed_entries: number
  }
  locations: string[]
  skus: string[]
  /** False when migration 0011 hasn't been run; the page says so instead of erroring. */
  inventory_enabled: boolean
  /** Whether the server can host photos (Supabase credentials present). False makes
   *  the edit dialog explain itself rather than offering an uploader that fails. */
  photo_hosting_enabled: boolean
}

/** One inventory row as a line in the eBay File Exchange CSV. Everything here was
 *  decided server-side — the price especially, which is derived in
 *  services/listing_csv.py so no pricing math ever lands in the browser. */
export interface ListingDraft {
  id: number
  name: string
  /** 80 characters or fewer, ending in the grade abbreviation that
   *  trading_api.resolve_condition reads back once the listing is live. */
  title: string
  price: number
  quantity: number
  sku: string | null
  condition: string | null
  /** eBay's own ungraded-condition wording, which is not the same vocabulary as
   *  the app's grades. Blank when the row's condition maps to neither. */
  card_condition: string
  value_status: InventoryItem['value_status']
  unit_value: number
  /** Pipe-separated links, straight from the row. eBay rejects a listing with no
   *  photo (21919136), so an empty one carries a warning. */
  photo_urls: string
  /** Things worth knowing before uploading — a title that will never get an
   *  automatic price, a grade eBay won't recognise, a price raised to the floor. */
  warnings: string[]
}

/** A selected row that can't become a listing, and why. */
export interface ListingSkip {
  id: number
  name: string
  reason: string
}

/** Which of eBay's two templates to build. 'draft' lands rows in
 *  ebay.com/sh/lst/drafts to finish in the listing tool and needs no business
 *  policies at all; 'add' creates the listings outright and needs all four
 *  Settings fields. */
export type ListingCsvMode = 'draft' | 'add'

export interface ListingCsvResponse {
  mode: ListingCsvMode
  /** The whole file. Empty string when nothing was listable. Always a CSV — eBay
   *  rejects a workbook for both of these templates ("stick to commas, semicolons,
   *  or tabs"); only the separate prefill template is an .xlsx. */
  csv: string
  drafts: ListingDraft[]
  skipped: ListingSkip[]
  /** Postage the price floor assumed for the chosen shipping profile. $0 for a
   *  profile SHIPPING_PRICE_MAP doesn't know, which is worth showing. */
  shipping_charge: number
  filename: string
}

/** Standing listing settings, the four things the CSV needs that an inventory row
 *  can't know. Stored per user (migration 0015), not per browser: a policy name
 *  that doesn't match Seller Hub is the commonest reason an upload is rejected, so
 *  getting it right once should hold on every machine you sign in from. */
export interface ListingDefaults {
  /** ZIP or city eBay shows buyers. */
  item_location: string
  /** Must stay a name SHIPPING_PRICE_MAP knows, or the CSV's price floor assumes
   *  postage is free. */
  shipping_profile: string
  payment_profile: string
  return_profile: string
  /** Optional, unlike the four above - never gates the CSV (migration 0018). Null
   *  means no seller-set minimum; when set, the Listing CSV button won't open a
   *  listing below it even when fees/postage alone would allow less. */
  min_price: number | null
}

/** Which of eBay's blank prefill templates is on file. Never the workbook itself —
 *  only the export endpoint reads those bytes. */
export interface PrefillTemplateMeta {
  name: string
  uploaded_at: string | null
  size: number
}

export interface ListingDefaultsResponse {
  listing_defaults: ListingDefaults
  /** False until db/migrations/0015_listing_defaults.sql has been run. */
  listing_defaults_enabled: boolean
  /** Fields still to fill in. A CSV can't be built while this is non-empty. */
  missing: (keyof ListingDefaults)[]
  /** Null when none is stored — and also when migration 0017 hasn't been run, since
   *  both leave the page asking for a file. */
  prefill_template: PrefillTemplateMeta | null
}

/** What `PUT /settings/listing-defaults` adds on top: how many inventory rows it just
 *  raised to a newly-saved minimum (0 when min_price is null, or nothing was below
 *  it). Only this endpoint enforces the minimum against the existing pile - a plain
 *  GET never mutates anything, so it doesn't carry this field. */
export interface ListingDefaultsSaveResponse extends ListingDefaultsResponse {
  raised_to_minimum: number
}

/** What `PUT /settings/prefill-template` adds on top: what it found in the file it
 *  just accepted, so a template eBay has revised is visible immediately. */
export interface PrefillTemplateUpload extends ListingDefaultsResponse {
  sheet: string
  columns: string[]
  missing_columns: string[]
}

/** One inventory row as a line in eBay's prefill listing template. No price: that
 *  flow only asks what the item IS, and the price is set later. */
export interface PrefillDraft {
  id: number
  name: string
  /** The lot SKU, deliberately not unique per row — routers/lots.py groups all
   *  money by exactly this string. */
  custom_label: string
  /** Pipe-separated https:// links, capped at eBay's 24. */
  photo_urls: string
  title: string
  category: string
  /** `Name=Value` pairs joined by pipes, empty values dropped. */
  aspects: string
  warnings: string[]
}

export interface PrefillResponse {
  /** The filled workbook, base64-encoded — the same file that was uploaded, with
   *  rows written into it and every other sheet and style untouched. */
  workbook: string
  filename: string
  drafts: PrefillDraft[]
  skipped: ListingSkip[]
  /** The sheet that was written to, and the first row written. */
  sheet: string
  first_row: number
  /** Which of the five known columns the template actually had, and which it
   *  didn't — a template missing the photo or aspects column still works. */
  columns: string[]
  missing_columns: string[]
}
