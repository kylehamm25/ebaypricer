import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, X } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api, apiPost } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { StageRefreshButton } from '../components/shared/StageRefreshButton'
import { CardArt, GridShell, ViewToggle } from '../components/shared/ViewToggle'
import { GRID_CLASS, useViewPreference } from '../lib/view-preference'
import { useChartCursor } from '../lib/theme'
import { formatCurrency, formatInt, formatSuggestionReason, toNumber } from '../lib/utils'
import type {
  ActiveListing, ActiveSummary, PriceComparison, SuggestedPriceBasis, ValueBucketResponse,
} from '../types'

interface BulkPriceResult {
  applied: number
  failed: number
  results: { item_id: string; status: string; error?: string }[]
}

// Must stay <= MAX_BULK_ITEMS in dashboard/backend/routers/active.py - selections
// larger than one chunk are split into sequential requests instead of erroring out.
const BULK_CHUNK_SIZE = 100

// Mostly the same keys and order as the table's column headers below, and the same
// keys routers/active.py accepts in _SORT_COLS - plus "Type", which like the
// inventory page's sort of the same name has no column of its own (card type is
// resolved from the catalog, not stored) and is sorted server-side in Python.
// The grid has no headers to click at all, so it needs sorting spelled out
// explicitly here; the table's own headers cover every one of these except
// "Card #" and "Card Type", which have no column of their own (the number is
// derived from the matched card, the type from the catalog, neither is shown
// anywhere on the page) - so this control stays visible in both views rather
// than only where the grid's missing headers would otherwise leave no way to
// trigger those two.
const SORTS: { key: string; label: string }[] = [
  { key: 'Number', label: 'Card #' },
  { key: 'Type', label: 'Card Type' },
  { key: 'Card', label: 'Title' },
  { key: 'Condition', label: 'Condition' },
  { key: 'Price', label: 'Price' },
  { key: 'Total', label: 'Total' },
  { key: 'Active Avg', label: 'Active Avg' },
  { key: 'Suggested Price', label: 'Suggested' },
  { key: 'Days Listed', label: 'Days Listed' },
  { key: 'Watchers', label: 'Watchers' },
  { key: 'Search Position', label: 'Search Rank' },
]

/** One live listing as a tile: art on top, the numbers under it, nothing editable.
 *  Selection is offered only where there is a suggested price to apply, exactly as
 *  in the table - a checkbox on a listing with nothing to change would arm a bulk
 *  action that then skipped it. */
function ActiveCard({ item, selectable, selected, onToggle, onOpen }: {
  item: ActiveListing
  selectable: boolean
  selected: boolean
  onToggle: () => void
  onOpen: () => void
}) {
  const price = toNumber(item.Price)
  const suggested = toNumber(item['Suggested Price'])
  const delta = price != null && suggested != null ? suggested - price : null

  return (
    <GridShell selected={selected} onClick={onOpen} label={`Open ${item.Title}`}>
      {/* Tints with the tile, so hovering lights the whole block rather than
          leaving the picture sitting on its own untouched panel. */}
      <div className="relative bg-slate-50 dark:bg-neutral-900/40 transition-colors group-hover:bg-slate-100 dark:group-hover:bg-neutral-700">
        <CardArt artUrl={item.card_image_url} className="w-full" />
        {selectable && (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            // The tile itself opens the listing, so ticking must not also navigate.
            onClick={(e) => e.stopPropagation()}
            aria-label="Select for bulk price update"
            className="absolute top-2 left-2 w-5 h-5 cursor-pointer rounded accent-blue-600 bg-white dark:bg-neutral-800 shadow"
          />
        )}
      </div>

      <div className="flex flex-col gap-1 p-2">
        <div
          className="text-sm font-medium text-slate-800 dark:text-neutral-100 truncate"
          title={item.Title as string}
        >
          {item.Title}
        </div>
        <div className="flex items-center justify-between gap-2 text-xs text-slate-400">
          <span className="truncate">
            {[item.Condition, item.SKU].filter(Boolean).join(' · ') || '—'}
          </span>
          {/* Same ×n as the inventory tile: multi-quantity listings matter here,
              since applying a suggested price moves every unit. */}
          <span className="tabular-nums shrink-0">×{formatInt(item.Quantity)}</span>
        </div>

        <div className="flex items-end justify-between gap-2">
          <span className="text-sm tabular-nums text-slate-800 dark:text-neutral-100">
            {formatCurrency(price)}
          </span>
          {/* The suggested price as a delta, not a second absolute number - what
              matters on a tile is whether it wants to move and which way. */}
          {delta != null && Math.abs(delta) >= 0.01 ? (
            <span
              className={`text-xs tabular-nums ${
                delta > 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-rose-600 dark:text-rose-400'
              }`}
              title={`Suggested ${formatCurrency(suggested)}`}
            >
              {delta > 0 ? '+' : ''}{formatCurrency(delta)}
            </span>
          ) : (
            <span className="text-xs text-slate-400">—</span>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-neutral-400">
          <span>{formatInt(item['Days Listed'])}d</span>
          <span>{formatInt(item.Watchers)} watching</span>
        </div>
      </div>
    </GridShell>
  )
}

export function ActiveListingsPage() {
  const cursor = useChartCursor()
  const [view, chooseView] = useViewPreference('active')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [reviewOpen, setReviewOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get('page') ?? '1')
  const cardFilter = searchParams.get('card') ?? ''
  // Card number, ascending, is the default on a fresh open - matches
  // dashboard/backend/routers/active.py's own Query() defaults, so a direct API call
  // with no params agrees with what a fresh page load shows.
  const sortBy = searchParams.get('sort_by') ?? 'Number'
  const sortDir = (searchParams.get('sort_dir') === 'desc' ? 'desc' : 'asc') as 'asc' | 'desc'
  const perPageOptions = [50, 100, 250, 500]
  const rawPerPage = Number(searchParams.get('per_page') ?? '500')
  const perPage = perPageOptions.includes(rawPerPage) ? rawPerPage : 500

  // Updates the URL query string so filters/sort/page survive navigating
  // away and back (component unmounts on route change and would otherwise
  // lose plain useState). null/'' clears the param instead of writing it.
  const updateParams = (updates: Record<string, string | null>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === '') next.delete(key)
        else next.set(key, value)
      }
      return next
    }, { replace: true })
  }
  const setPage = (value: number | ((p: number) => number)) => {
    const nextPage = typeof value === 'function' ? value(page) : value
    updateParams({ page: nextPage > 1 ? String(nextPage) : null })
  }
  // Clicking the header a column is already sorted by flips direction; clicking a
  // different one switches to it, defaulting to desc (matches the old dropdown default).
  const handleSort = (key: string) => {
    updateParams(
      sortBy === key
        ? { sort_dir: sortDir === 'desc' ? 'asc' : 'desc', page: null }
        : { sort_by: key, sort_dir: 'desc', page: null }
    )
  }

  const listQuery = useQuery({
    queryKey: ['active-list', page, cardFilter, sortBy, sortDir, perPage],
    queryFn: () =>
      api(
        `/active/list?page=${page}&per_page=${perPage}` +
        (cardFilter ? `&card=${encodeURIComponent(cardFilter)}` : '') +
        `&sort_by=${encodeURIComponent(sortBy)}&sort_dir=${sortDir}`
      ),
    // Sorting/paging/filtering only reorders the same listings, so keep showing the
    // current rows while the new page loads instead of tearing the table down to a
    // skeleton. The skeleton then only appears on the genuine first load.
    placeholderData: keepPreviousData,
  })
  const { data: rawList, isLoading: listLoading, isPlaceholderData } = listQuery

  const resetFilters = () => {
    setSearchParams({}, { replace: true })
  }

  const hasFilters = !!(cardFilter || sortBy !== 'Number' || sortDir !== 'asc')

  const { data: summary } = useQuery<ActiveSummary>({
    queryKey: ['active-summary'],
    queryFn: () => api('/active/summary'),
  })

  const { data: comparisons } = useQuery<PriceComparison[]>({
    queryKey: ['pricing-comparisons'],
    queryFn: () => api('/pricing/comparisons'),
    refetchInterval: 120_000,
  })

  const { data: valueBuckets } = useQuery<ValueBucketResponse>({
    queryKey: ['active-value-buckets'],
    queryFn: () => api('/active/value-buckets'),
  })

  const { data: valueTrend } = useQuery<{ date: string; total_value: number; total_listings: number }[]>({
    queryKey: ['active-value-trend'],
    queryFn: () => api('/active/value-trend'),
  })

  // With a single history point the line chart would render as a lone dot;
  // extend a flat line from the day before at the same value so the line
  // visibly comes in from the left until real history accumulates.
  const trendData = (valueTrend?.length ?? 0) > 1
    ? valueTrend
    : (valueTrend ?? []).map((only) => {
        const prev = new Date(`${only.date}T00:00:00Z`)
        prev.setUTCDate(prev.getUTCDate() - 1)
        return [
          { ...only, date: prev.toISOString().slice(0, 10) },
          only,
        ]
      }).flat()

  const listData = rawList as { items: ActiveListing[]; total: number; page: number; per_page: number } | undefined
  const totalPages = listData ? Math.ceil(listData.total / listData.per_page) : 0

  const pricingMap = new Map<string, PriceComparison>()
  comparisons?.forEach(c => pricingMap.set(c.card_query, c))

  // Exact lookup on the row's already-matched Card field - comparisons' card_query is
  // literally the same string (collect_cards_needing_research() reads it straight from
  // active_listings.card), so no fuzzy matching is needed or safe here. The previous
  // fuzzy title/word-overlap version could match a listing to a completely unrelated
  // card's pricing whenever they shared a common word (e.g. "reverse", "holo"),
  // collapsing dozens of distinct cards onto the same wrong Sold Avg/Spread/Suggested.
  const getPricingForListing = (card: string | null | undefined) => {
    if (!card) return null
    return pricingMap.get(card) ?? null
  }

  // Bulk apply: review the batch, then confirm. Never applies without an explicit
  // second click - these are live eBay listings.
  const selectedRows = (listData?.items ?? []).filter((r) => selected.has(r['Item ID'] as string))

  const isPriceChanged = (r: ActiveListing) => {
    const suggested = r['Suggested Price'] != null ? Number(r['Suggested Price']) : null
    const current = r.Price != null ? Number(r.Price) : null
    return suggested !== null && (current === null || Math.abs(suggested - current) >= 0.01)
  }
  const eligibleIds = (listData?.items ?? []).filter(isPriceChanged).map((r) => r['Item ID'] as string)
  const allEligibleSelected = eligibleIds.length > 0 && eligibleIds.every((id) => selected.has(id))
  const toggleSelectAll = (checked: boolean) => {
    const next = new Set(selected)
    eligibleIds.forEach((id) => (checked ? next.add(id) : next.delete(id)))
    setSelected(next)
  }
  const removeFromSelection = (id: string) => {
    const next = new Set(selected)
    next.delete(id)
    setSelected(next)
  }

  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null)

  const bulkMutation = useMutation({
    mutationFn: async () => {
      const items = selectedRows.map((r) => ({
        item_id: r['Item ID'] as string,
        price: Number(r['Suggested Price']),
      }))
      const merged: BulkPriceResult = { applied: 0, failed: 0, results: [] }
      setBulkProgress({ done: 0, total: items.length })
      // Chunked so a selection over the backend's per-request cap (currently 100)
      // still goes through, instead of the whole batch being rejected up front.
      for (let i = 0; i < items.length; i += BULK_CHUNK_SIZE) {
        const chunk = items.slice(i, i + BULK_CHUNK_SIZE)
        const res = (await apiPost('/active/bulk-price', { items: chunk })) as BulkPriceResult
        merged.applied += res.applied
        merged.failed += res.failed
        merged.results.push(...res.results)
        setBulkProgress({ done: Math.min(i + BULK_CHUNK_SIZE, items.length), total: items.length })
      }
      return merged
    },
    onSuccess: (res) => {
      setBulkProgress(null)
      if (res.failed === 0) {
        setReviewOpen(false)
        setSelected(new Set())
      }
      queryClient.invalidateQueries({ queryKey: ['active-list'] })
      queryClient.invalidateQueries({ queryKey: ['active-summary'] })
      queryClient.invalidateQueries({ queryKey: ['pricing-comparisons'] })
    },
    onError: () => setBulkProgress(null),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Active Listings</h1>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <button
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
              onClick={() => { bulkMutation.reset(); setBulkProgress(null); setReviewOpen(true) }}
            >
              Apply {selected.size} suggested {selected.size === 1 ? 'price' : 'prices'}
            </button>
          )}
          <StageRefreshButton
            statusPath="/active/refresh/status"
            runPath="/active/refresh"
            label="Refresh from eBay"
            onRefreshed={() => {
              queryClient.invalidateQueries({ queryKey: ['active-list'] })
              queryClient.invalidateQueries({ queryKey: ['active-summary'] })
              queryClient.invalidateQueries({ queryKey: ['pricing-comparisons'] })
              queryClient.invalidateQueries({ queryKey: ['active-value-buckets'] })
              queryClient.invalidateQueries({ queryKey: ['active-value-trend'] })
            }}
          />
        </div>
      </div>

      {reviewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 max-w-2xl w-full max-h-[80vh] flex flex-col">
            <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100 mb-1">
              Review price changes
            </h2>
            <p className="text-xs text-slate-500 dark:text-neutral-400 mb-4">
              These will be applied to your live eBay listings. Price only — Best Offer
              auto-accept and minimum offer settings are left as they are.
            </p>
            <div className="overflow-y-auto flex-1 -mx-1 px-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-400 dark:text-neutral-500">
                    <th className="text-left font-medium pb-1 pr-3">Title</th>
                    <th className="text-right font-medium pb-1 px-2" colSpan={3}>Price</th>
                    <th className="text-right font-medium pb-1 pl-3">Avg listed</th>
                    <th className="pb-1" />
                    <th className="pb-1" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-neutral-700">
                  {[...selectedRows]
                    .sort((a, b) => {
                      const diffA = Math.abs(Number(a['Suggested Price']) - Number(a.Price))
                      const diffB = Math.abs(Number(b['Suggested Price']) - Number(b.Price))
                      return diffB - diffA
                    })
                    .map((r) => {
                    const id = r['Item ID'] as string
                    const from = Number(r.Price)
                    const to = Number(r['Suggested Price'])
                    const result = bulkMutation.data?.results.find((x) => x.item_id === id)
                    // Same source as the Active Avg column on the list behind this
                    // modal: the mean of today's competitor listings for this card.
                    // Here it's the sanity check on the new price - is it landing
                    // near the market or well off it?
                    const avgListed = getPricingForListing(r.Card as string | null)?.active_avg ?? null
                    const vsAvgPct = avgListed ? Math.round(((to - avgListed) / avgListed) * 100) : null
                    return (
                      <tr key={id}>
                        <td className="py-2 pr-3 max-w-sm truncate text-slate-700 dark:text-neutral-200">{r.Title as string}</td>
                        <td className="py-2 px-2 text-right tabular-nums text-slate-500 dark:text-neutral-400">{formatCurrency(from)}</td>
                        <td className="py-2 px-1 text-slate-400">→</td>
                        <td className={`py-2 pl-1 text-right tabular-nums font-medium ${to < from ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                          {formatCurrency(to)}
                        </td>
                        <td
                          className="py-2 pl-3 text-right tabular-nums text-slate-500 dark:text-neutral-400"
                          title={
                            avgListed
                              ? `Average asking price across current competitor listings for this card.`
                                + ` New price is ${vsAvgPct === 0 ? 'level with' : `${Math.abs(vsAvgPct as number)}% ${(vsAvgPct as number) > 0 ? 'above' : 'below'}`} it.`
                              : 'No competitor listings found for this card'
                          }
                        >
                          {avgListed ? formatCurrency(avgListed) : <span className="text-slate-400 text-xs">—</span>}
                        </td>
                        <td className="py-2 pl-3 text-xs max-w-[220px]">
                          {result?.status === 'ok' && <span className="text-emerald-600 dark:text-emerald-400">applied</span>}
                          {result?.status === 'error' && (
                            <span className="text-rose-600 dark:text-rose-400" title={result.error}>
                              failed{result.error ? `: ${result.error}` : ''}
                            </span>
                          )}
                        </td>
                        <td className="py-2 pl-2 text-right">
                          {!bulkMutation.data && (
                            <button
                              onClick={() => removeFromSelection(id)}
                              disabled={bulkMutation.isPending}
                              className="p-1 rounded-md text-slate-300 hover:text-rose-600 hover:bg-rose-50 dark:text-neutral-600 dark:hover:text-rose-400 dark:hover:bg-rose-500/10 disabled:opacity-30"
                              title="Remove from this batch"
                              aria-label={`Remove ${r.Title as string} from batch`}
                            >
                              <X size={14} />
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {selectedRows.length === 0 && (
                <p className="text-center text-sm text-slate-400 py-6">No items left in this batch.</p>
              )}
            </div>
            {bulkMutation.isError && (
              <p className="text-xs text-rose-600 dark:text-rose-400 mt-3">
                {(bulkMutation.error as Error).message}
              </p>
            )}
            {bulkMutation.data && bulkMutation.data.failed > 0 && (
              <p className="text-xs text-rose-600 dark:text-rose-400 mt-3">
                {bulkMutation.data.applied} applied, {bulkMutation.data.failed} failed. Successful changes are saved; close and retry the rest.
              </p>
            )}
            <div className="flex justify-end gap-2 pt-4">
              <button
                className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
                onClick={() => setReviewOpen(false)}
                disabled={bulkMutation.isPending}
              >
                {bulkMutation.data ? 'Close' : 'Cancel'}
              </button>
              <button
                className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
                onClick={() => bulkMutation.mutate()}
                disabled={bulkMutation.isPending || !!bulkMutation.data || selectedRows.length === 0}
              >
                {bulkMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                {bulkMutation.isPending
                  ? `Applying${bulkProgress ? ` ${bulkProgress.done}/${bulkProgress.total}` : '...'}`
                  : `Apply ${selectedRows.length}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {summary ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <KpiCard title="Total Listings" value={formatInt(summary.total_listings)} />
          <KpiCard title="Total Value" value={formatCurrency(summary.total_value)} />
          <KpiCard title="Avg Days Listed" value={`${Math.round(summary.avg_days_listed)}d`} />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {!valueBuckets || !valueTrend ? (
          <>
            <ChartSkeleton height={320} />
            <ChartSkeleton height={320} />
          </>
        ) : (
          <>
        {valueBuckets && valueBuckets.buckets.length > 0 && (
          <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 mb-3">Inventory by Value Range</h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={valueBuckets.buckets}>
                <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} domain={[0, 100]} />
                <Tooltip
                  cursor={cursor.bar}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const b = payload[0].payload as ValueBucketResponse['buckets'][number]
                    return (
                      <div className="bg-white dark:bg-neutral-800 border border-slate-200 dark:border-neutral-700 rounded-md shadow-sm px-3 py-2 text-xs">
                        <p className="font-semibold text-slate-700 dark:text-neutral-200 mb-1">${b.bucket}</p>
                        <p className="text-slate-600 dark:text-neutral-300">{b.count} listings ({b.count_pct}%)</p>
                        <p className="text-slate-600 dark:text-neutral-300">{formatCurrency(b.value)} value ({b.value_pct}%)</p>
                      </div>
                    )
                  }}
                />
                <Bar dataKey="count_pct" fill="#3b82f6" radius={[2, 2, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {valueTrend && valueTrend.length > 0 && (
          <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 mb-3">Total Inventory Value Over Time</h2>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={trendData}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v).toFixed(0)}`} />
                <Tooltip cursor={cursor.line} formatter={(v) => formatCurrency(Number(v))} />
                <Line
                  type="monotone"
                  dataKey="total_value"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ r: 4, fill: '#3b82f6', strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
          </>
        )}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          placeholder="Filter by card..."
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm w-52"
          value={cardFilter}
          onChange={(e) => updateParams({ card: e.target.value, page: null })}
        />
        {hasFilters && (
          <button
            className="text-xs text-blue-600 hover:underline"
            onClick={resetFilters}
          >
            Clear
          </button>
        )}
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={`${sortBy}:${sortDir}`}
          onChange={(e) => {
            const [key, dir] = e.target.value.split(':')
            updateParams({ sort_by: key, sort_dir: dir, page: null })
          }}
        >
          {SORTS.flatMap((o) => [
            <option key={`${o.key}:asc`} value={`${o.key}:asc`}>{o.label} ↑</option>,
            <option key={`${o.key}:desc`} value={`${o.key}:desc`}>{o.label} ↓</option>,
          ])}
        </select>
        <div className="ml-auto">
          <ViewToggle view={view} onChange={chooseView} />
        </div>
      </div>

      {listLoading ? (
        <TableSkeleton
          rows={8}
          columns={[
            { header: '', width: 'w-10' },
            { header: 'Title', width: 'w-44' },
            { header: 'Condition', width: 'w-20' },
            { header: 'Price', width: 'w-16' },
            { header: 'Total', width: 'w-16' },
            { header: 'Active Avg', width: 'w-14' },
            { header: 'Suggested', width: 'w-14' },
            { header: 'Days', width: 'w-10' },
            { header: 'Watchers', width: 'w-12' },
            { header: 'Qty', width: 'w-8' },
            { header: 'Search Rank', width: 'w-14' },
          ]}
        />
      ) : listData?.items ? (
        <>
          <div className={isPlaceholderData ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
          {view === 'grid' ? (
            listData.items.length === 0 ? (
              <div className="bg-white dark:bg-neutral-800 rounded-xl p-8 text-center text-slate-400 text-sm">
                No data
              </div>
            ) : (
              <div className={GRID_CLASS}>
                {listData.items.map((r) => {
                  const id = r['Item ID'] as string
                  return (
                    <ActiveCard
                      key={id}
                      item={r}
                      selectable={isPriceChanged(r)}
                      selected={selected.has(id)}
                      onToggle={() => {
                        const next = new Set(selected)
                        if (next.has(id)) next.delete(id)
                        else next.add(id)
                        setSelected(next)
                      }}
                      onOpen={() => navigate(`/active/${encodeURIComponent(id)}`)}
                    />
                  )
                })}
              </div>
            )
          ) : (
          <DataTable<ActiveListing>
            columns={[
              {
                key: 'sprite_url',
                header: '',
                className: 'w-30',
                // Real card art, sprite only as a fallback: the species sprite can't
                // tell two printings apart - every Charizard shares one.
                render: (r) => (
                  <CardArt artUrl={r.card_image_url} className="w-16 rounded" />
                ),
              },
              { key: 'Title', header: 'Title', className: 'max-w-sm truncate', sortKey: 'Card' },
              { key: 'Condition', header: 'Condition', sortKey: 'Condition' },
              { key: 'Price', header: 'Price', render: (r) => formatCurrency(r.Price as string), sortKey: 'Price' },
              {
                key: 'total',
                // normal-case on the label itself, not the cell: DataTable uppercases
                // every th, and text-transform on a child wins over the inherited value
                // regardless of how Tailwind happens to order the two utilities.
                header: <span className="normal-case">Total</span>,
                sortKey: 'Total',
                render: (r) => {
                  const price = toNumber(r.Price)
                  if (price === null) return <span className="text-slate-400 text-xs">—</span>
                  const shipping = toNumber(r['Shipping Charge']) ?? 0
                  return formatCurrency(price + shipping)
                },
              },
              {
                key: 'active_avg',
                header: <span className="normal-case">Active Avg</span>,
                sortKey: 'Active Avg',
                render: (r) => {
                  const pricing = getPricingForListing(r.Card as string | null)
                  if (!pricing?.active_avg) return <span className="text-slate-400 text-xs">—</span>
                  // Landed, so it lines up with the Total column beside it rather than
                  // making a free-shipping listing look dear next to a cheaper item
                  // that charges postage. Falls back to the item price when no comp
                  // reported shipping - the tooltip says which of the two you're
                  // looking at, since the number alone can't.
                  const landed = pricing.active_avg_total
                  return (
                    <span
                      className="tabular-nums"
                      title={
                        landed !== null
                          ? `${formatCurrency(pricing.active_avg)} item + ${formatCurrency(pricing.avg_shipping)} shipping, across ${pricing.active_sample ?? 0} competitor listings`
                          : `Item price only - no competitor reported a shipping cost (${pricing.active_sample ?? 0} listings)`
                      }
                    >
                      {formatCurrency(landed ?? pricing.active_avg)}
                    </span>
                  )
                },
              },
              {
                key: 'suggested',
                header: 'Suggested',
                sortKey: 'Suggested Price',
                render: (r) => {
                  const suggested = r['Suggested Price'] != null ? Number(r['Suggested Price']) : null
                  if (suggested === null) {
                    const basis = r['Suggested Price Basis'] as SuggestedPriceBasis | null
                    // "held" distinguishes a recently-repriced listing (deliberately not
                    // re-suggested yet) from one we simply have no suggestion for.
                    return (
                      <span className="text-slate-400 text-xs" title={formatSuggestionReason(basis)}>
                        {basis?.status === 'cooldown' ? 'held' : '—'}
                      </span>
                    )
                  }
                  const current = r.Price != null ? Number(r.Price) : null
                  const tone = current === null || current <= suggested ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
                  const basis = r['Suggested Price Basis'] as SuggestedPriceBasis | null
                  const lowConfidence = basis?.flags?.includes('low_confidence')
                  return (
                    <span className={`text-xs font-medium ${tone}`} title={formatSuggestionReason(basis)}>
                      {formatCurrency(suggested)}
                      {lowConfidence && <span className="ml-1 text-slate-400" title="Few competitor listings">?</span>}
                    </span>
                  )
                },
              },
              { key: 'Days Listed', header: 'Days', render: (r) => formatInt(r['Days Listed'] as string), sortKey: 'Days Listed' },
              { key: 'Watchers', header: 'Watchers', render: (r) => formatInt(r.Watchers as string), sortKey: 'Watchers' },
              { key: 'Quantity', header: 'Qty', render: (r) => formatInt(r.Quantity as string) },
              {
                key: 'Search Position',
                header: 'Search Rank',
                render: (r) => r['Search Position'] ? formatInt(r['Search Position'] as string) : <span className="text-slate-400 text-xs">—</span>,
                sortKey: 'Search Position',
              },
              {
                key: 'select',
                header: (
                  <input
                    type="checkbox"
                    className="w-4 h-4 cursor-pointer accent-blue-600"
                    checked={allEligibleSelected}
                    disabled={eligibleIds.length === 0}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => toggleSelectAll(e.target.checked)}
                    aria-label="Select all suggested prices"
                    title="Select all suggested prices"
                  />
                ),
                className: 'w-10 pr-6',
                stopRowClick: true,
                render: (r) => {
                  if (!isPriceChanged(r)) return null
                  const id = r['Item ID'] as string
                  return (
                    <input
                      type="checkbox"
                      className="w-4 h-4 cursor-pointer accent-blue-600"
                      checked={selected.has(id)}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const next = new Set(selected)
                        if (e.target.checked) next.add(id)
                        else next.delete(id)
                        setSelected(next)
                      }}
                      aria-label="Select for bulk price update"
                    />
                  )
                },
              },
            ]}
            data={listData.items}
            keyField="Item ID"
            onRowClick={(r) => navigate(`/active/${encodeURIComponent(r['Item ID'] as string)}`)}
            sortBy={sortBy}
            sortDir={sortDir}
            onSortChange={handleSort}
          />
          )}
          </div>
          <div className="flex justify-center items-center pt-2 relative">
            <div className="flex gap-2 items-center">
              <button
                className="px-3 py-1 text-sm border rounded-md disabled:opacity-30"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </button>
              <span className="text-sm text-slate-500 dark:text-neutral-400">
                Page {page} of {totalPages} ({listData.total} total)
              </span>
              <button
                className="px-3 py-1 text-sm border rounded-md disabled:opacity-30"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
            <label className="absolute right-0 flex items-center gap-2 text-sm text-slate-500 dark:text-neutral-400">
              Show
              <select
                className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1 text-sm bg-white"
                value={perPage}
                onChange={(e) => updateParams({ per_page: e.target.value, page: null })}
              >
                {perPageOptions.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
              per page
            </label>
          </div>
        </>
      ) : null}
    </div>
  )
}