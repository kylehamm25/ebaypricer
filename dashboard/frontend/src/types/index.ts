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
  status: 'ok' | 'thin_comps' | 'no_comps'
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
