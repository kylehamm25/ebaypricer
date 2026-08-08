export interface DashboardKpis {
  sold_items: number
  revenue: number
  shipping: number
  fees: number
  active_listings: number
  trends: { day: string; count: number; revenue: number }[]
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
  active_sample: number | null
  spread: number | null
}

export interface CardPriceDetail {
  card_query: string
  matched_query?: string | null
  price_snapshots: Record<string, unknown>[]
  active_snapshots: Record<string, unknown>[]
  recent_sold: Record<string, unknown>[]
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
