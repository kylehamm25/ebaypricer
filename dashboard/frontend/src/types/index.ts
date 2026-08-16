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
  total_earnings: number
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
  status: 'ok' | 'cooldown' | 'thin_comps' | 'no_comps' | 'excluded'
  matched_keyword?: string
  /** status 'cooldown': this listing was repriced recently and is not re-suggested
   *  until cooldown_days have passed. See REPRICE_COOLDOWN_DAYS in suggested_price.py. */
  days_since_price_change?: number
  cooldown_days?: number
  anchor_avg?: number
  anchor_floor?: number
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
  sprite_url?: string
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
