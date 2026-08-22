export interface DashboardKpis {
  month: string
  available_months: string[]
  sold_items: number
  revenue: number
  shipping: number
  fees: number
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
  /** Real per-order net from the Finances API (gross - fees - debits), not revenue minus fees. */
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
  sold_weighted_avg: number | null
  sold_sample: number | null
  active_avg: number | null
  active_min: number | null
  active_sample: number | null
  spread: number | null
}

export interface PriceSnapshot {
  card_query: string
  snapshot_date: string
  sample_size: number | null
  avg_price: number | null
  median_price: number | null
  min_price: number | null
  max_price: number | null
  std_dev: number | null
  weighted_avg: number | null
}

export interface ActiveSnapshot {
  card_query: string
  snapshot_date: string
  sample_size: number | null
  avg_price: number | null
  min_price: number | null
  max_price: number | null
}

export interface SoldListing extends Record<string, unknown> {
  item_id?: string
  card_query?: string
  title: string
  price: number | null
  currency?: string | null
  condition: string | null
  listing_type: string | null
  sold_date: string | null
  url?: string | null
  pulled_at?: string | null
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
  price_snapshots: PriceSnapshot[]
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
  'Recent Sold Avg': number | string | null
  'Price vs Sold Avg': number | string | null
  'Recent Sold Count': number | string | null
  'Last Checked': string | null
  'Active Avg (Top 5)': number | string | null
  'Price Accuracy': number | string | null
  'Search Position': number | string | null
  'Suggested Price': number | string | null
  'Suggested Price At': string | null
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
  realized_profit: number
  projected_profit: number
  tracked_lots: number
  untracked_lots: number
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
  sprite_url?: string
}

export interface LotDetailResponse {
  lot: Lot
  sold: LotSoldRow[]
  active: LotActiveRow[]
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
