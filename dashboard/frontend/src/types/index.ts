export interface DashboardKpis {
  month: string
  available_months: string[]
  sold_items: number
  revenue: number
  shipping: number
  fees: number
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
  total_earnings: number
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
  snapshot_date?: string | null
  active_avg: number | null
  avg_shipping: number | null
  active_avg_total: number | null
  active_min: number | null
  active_max: number | null
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

export interface SuggestedPriceBasis {
  v: number
  status: 'ok' | 'cooldown' | 'thin_comps' | 'no_comps' | 'excluded' | 'comp_mismatch' | 'multi_card'
  matched_keyword?: string
  days_since_price_change?: number
  cooldown_days?: number
  anchor_avg?: number
  anchor_floor?: number
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
  shipping_charge?: number | null
  comp_avg_shipping?: number | null
  shipping_adjustment?: number
  ese_shipping?: boolean
  ese_max_price?: number
  watchers?: number | null
  watcher_pull?: number
  pre_guardrail?: number
  stale_hold?: boolean
  stale_no_increase_days?: number
  feedback_direction?: string | null
  days_since_feedback?: number | null
  feedback_hold_days?: number
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
  'Card Locked'?: boolean
  'Suggested Price Basis': SuggestedPriceBasis | null
  // Active thumbs-down on the suggestion, if any (null when never vetoed or expired).
  'Feedback'?: { direction: string; voted_at: string } | null
  sprite_url?: string
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

export interface Lot extends Record<string, unknown> {
  sku: string
  title?: string | null
  cost: number | null
  purchased_at: string | null
  source: string | null
  notes: string | null
  active_items: number
  listed_value: number
  unlisted_items: number
  unlisted_entries: number
  unlisted_value: number
  unlisted_unvalued: number
  sold_items: number
  sold_gross: number
  sold_net: number
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
  projected_profit: number
  tracked_lots: number
  untracked_lots: number
}

export interface LotOption {
  sku: string
  title?: string | null
}

export interface LotsResponse {
  lots: Lot[]
  totals: LotTotals
  cost_tracking_enabled: boolean
}

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
  pool_quality: { in: number; kept: number; dropped: number; reasons: Record<string, number>; soft_restored: boolean; identified: boolean } | null
  snapshot_date: string | null
  market_price: number | null
  search_url: string | null
  sprite_url: string | null
  condition: string | null
  condition_mult: number
  condition_known: boolean
  adjusted_value: number | null
  estimated_fees: number | null
  estimated_net: number | null
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
  card_query: string | null
  set_name: string | null
  number: string | null
  condition: string | null
  quantity: number
  location: string | null
  sku: string | null
  cost: number | null
  total_cost: number | null
  manual_value: number | null
  photo_urls: string | null
  notes: string | null
  created_at: string | null
  archived_at: string | null
  card_image_url: string | null
  search_url: string | null
  unit_value: number | null
  total_value: number | null
  value_status: 'ok' | 'manual' | 'unresearched' | 'no_card'
  value_date: string | null
  comps: number | null
  condition_known: boolean
  pool_filtered: boolean | null
}

export interface InventoryResponse {
  items: InventoryItem[]
  totals: {
    entries: number
    units: number
    value: number
    valued_entries: number
    cost: number
    costed_entries: number
  }
  locations: string[]
  skus: string[]
  inventory_enabled: boolean
  photo_hosting_enabled: boolean
}

export interface ImportCandidate {
  card_query: string
  name: string
  set_name: string
  number: string
  rarity: string
  image_url: string | null
  score: number
  name_score: number
  number_match: boolean
  visual_score: number | null
}

export interface InventoryImport {
  id: number
  image_url: string
  back_image_url?: string | null
  source_filename: string | null
  status: 'pending' | 'failed' | 'confirmed' | 'dismissed'
  auto_added: boolean
  confidence: 'high' | 'medium' | 'low' | 'none'
  score: number | null
  card_detected: boolean
  ocr_text: string | null
  detected_name: string | null
  detected_number: string | null
  candidates: ImportCandidate[]
  chosen_card_query: string | null
  inventory_id: number | null
  error: string | null
  created_at: string | null
  updated_at: string | null
  auto_add_eligible: boolean
}

export interface InventoryImportsResponse {
  pending: InventoryImport[]
  recent: InventoryImport[]
  imports_enabled: boolean
  photo_hosting_enabled: boolean
  recognition_enabled: boolean
}

export interface ListingDraft {
  id: number
  name: string
  title: string
  price: number
  quantity: number
  sku: string | null
  condition: string | null
  card_condition: string
  value_status: InventoryItem['value_status']
  unit_value: number
  photo_urls: string
  warnings: string[]
}

export interface ListingSkip {
  id: number
  name: string
  reason: string
}

export type ListingCsvMode = 'draft' | 'add'

export interface ListingCsvResponse {
  mode: ListingCsvMode
  csv: string
  drafts: ListingDraft[]
  skipped: ListingSkip[]
  shipping_charge: number
  filename: string
}

export interface ListingDefaults {
  item_location: string
  shipping_profile: string
  payment_profile: string
  return_profile: string
  min_price: number | null
}

export interface PrefillTemplateMeta {
  name: string
  uploaded_at: string | null
  size: number
}

export interface ListingDefaultsResponse {
  listing_defaults: ListingDefaults
  listing_defaults_enabled: boolean
  missing: (keyof ListingDefaults)[]
  prefill_template: PrefillTemplateMeta | null
}

export interface ListingDefaultsSaveResponse extends ListingDefaultsResponse {
  raised_to_minimum: number
}

export interface PrefillTemplateUpload extends ListingDefaultsResponse {
  sheet: string
  columns: string[]
  missing_columns: string[]
}

export interface PrefillDraft {
  id: number
  name: string
  custom_label: string
  photo_urls: string
  title: string
  category: string
  aspects: string
  warnings: string[]
}

export interface PrefillResponse {
  workbook: string
  filename: string
  drafts: PrefillDraft[]
  skipped: ListingSkip[]
  sheet: string
  first_row: number
  columns: string[]
  missing_columns: string[]
}
