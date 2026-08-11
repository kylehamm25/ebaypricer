import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api, apiPost } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { StageRefreshButton } from '../components/shared/StageRefreshButton'
import { useChartCursor } from '../lib/theme'
import { formatCurrency, formatInt, formatSuggestionReason } from '../lib/utils'
import type {
  ActiveListing, ActiveSummary, PriceComparison, SuggestedPriceBasis, ValueBucketResponse,
} from '../types'

interface BulkPriceResult {
  applied: number
  failed: number
  results: { item_id: string; status: string; error?: string }[]
}

export function ActiveListingsPage() {
  const cursor = useChartCursor()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [reviewOpen, setReviewOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get('page') ?? '1')
  const cardFilter = searchParams.get('card') ?? ''
  const conditionFilter = searchParams.get('condition') ?? ''
  const sortBy = searchParams.get('sort_by') ?? 'Days Listed'
  const sortDir = (searchParams.get('sort_dir') === 'asc' ? 'asc' : 'desc') as 'asc' | 'desc'
  const perPageOptions = [50, 100, 250, 500]
  const rawPerPage = Number(searchParams.get('per_page') ?? '50')
  const perPage = perPageOptions.includes(rawPerPage) ? rawPerPage : 50

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

  const listQuery = useQuery({
    queryKey: ['active-list', page, cardFilter, conditionFilter, sortBy, sortDir, perPage],
    queryFn: () =>
      api(
        `/active/list?page=${page}&per_page=${perPage}` +
        (cardFilter ? `&card=${encodeURIComponent(cardFilter)}` : '') +
        (conditionFilter ? `&condition=${encodeURIComponent(conditionFilter)}` : '') +
        `&sort_by=${encodeURIComponent(sortBy)}&sort_dir=${sortDir}`
      ),
  })
  const { data: rawList, isLoading: listLoading } = listQuery

  const { data: conditions } = useQuery<{ condition: string; count: number }[]>({
    queryKey: ['active-conditions'],
    queryFn: () => api('/active/by-condition'),
  })

  const resetFilters = () => {
    setSearchParams({}, { replace: true })
  }

  const hasFilters = !!(cardFilter || conditionFilter || sortBy !== 'Days Listed' || sortDir !== 'desc')

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

  const bulkMutation = useMutation({
    mutationFn: () =>
      apiPost('/active/bulk-price', {
        items: selectedRows.map((r) => ({
          item_id: r['Item ID'] as string,
          price: Number(r['Suggested Price']),
        })),
      }) as Promise<BulkPriceResult>,
    onSuccess: (res) => {
      if (res.failed === 0) {
        setReviewOpen(false)
        setSelected(new Set())
      }
      queryClient.invalidateQueries({ queryKey: ['active-list'] })
      queryClient.invalidateQueries({ queryKey: ['active-summary'] })
      queryClient.invalidateQueries({ queryKey: ['pricing-comparisons'] })
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Active Listings</h1>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <button
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
              onClick={() => { bulkMutation.reset(); setReviewOpen(true) }}
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
              queryClient.invalidateQueries({ queryKey: ['active-conditions'] })
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
              These will be applied to your live eBay listings.
            </p>
            <div className="overflow-y-auto flex-1 -mx-1 px-1">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-slate-100 dark:divide-neutral-700">
                  {selectedRows.map((r) => {
                    const id = r['Item ID'] as string
                    const from = Number(r.Price)
                    const to = Number(r['Suggested Price'])
                    const result = bulkMutation.data?.results.find((x) => x.item_id === id)
                    return (
                      <tr key={id}>
                        <td className="py-2 pr-3 max-w-sm truncate text-slate-700 dark:text-neutral-200">{r.Title as string}</td>
                        <td className="py-2 px-2 text-right tabular-nums text-slate-500 dark:text-neutral-400">{formatCurrency(from)}</td>
                        <td className="py-2 px-1 text-slate-400">→</td>
                        <td className={`py-2 pl-1 text-right tabular-nums font-medium ${to < from ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                          {formatCurrency(to)}
                        </td>
                        <td className="py-2 pl-3 text-xs">
                          {result?.status === 'ok' && <span className="text-emerald-600 dark:text-emerald-400">applied</span>}
                          {result?.status === 'error' && <span className="text-rose-600 dark:text-rose-400" title={result.error}>failed</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
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
                disabled={bulkMutation.isPending || !!bulkMutation.data}
              >
                {bulkMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                {bulkMutation.isPending ? 'Applying...' : `Apply ${selectedRows.length}`}
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
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={sortBy}
          onChange={(e) => updateParams({ sort_by: e.target.value, page: null })}
        >
          <option value="Days Listed">Sort: Days Listed</option>
          <option value="Price">Sort: Price</option>
          <option value="Watchers">Sort: Watchers</option>
          <option value="Card">Sort: Card</option>
          <option value="Search Position">Sort: Search Rank</option>
          <option value="Condition">Sort: Condition</option>
        </select>
        <button
          className={`border rounded-lg px-3 py-1.5 text-sm ${sortDir === 'desc' ? 'bg-slate-200 dark:bg-neutral-600 border-slate-300 dark:border-neutral-500' : 'border-slate-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-slate-600 dark:text-neutral-300'}`}
          title="Toggle sort direction"
          onClick={() => updateParams({ sort_dir: sortDir === 'desc' ? 'asc' : 'desc', page: null })}
        >
          {sortDir === 'desc' ? '↓ Desc' : '↑ Asc'}
        </button>
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={conditionFilter}
          onChange={(e) => updateParams({ condition: e.target.value, page: null })}
        >
          <option value="">All Conditions</option>
          {(conditions ?? []).map((c) => (
            <option key={c.condition} value={c.condition}>
              {c.condition} ({c.count})
            </option>
          ))}
        </select>
        {hasFilters && (
          <button
            className="text-xs text-blue-600 hover:underline"
            onClick={resetFilters}
          >
            Clear
          </button>
        )}
      </div>

      {listLoading ? (
        <TableSkeleton
          rows={8}
          columns={[
            { header: '', width: 'w-10' },
            { header: 'Title', width: 'w-44' },
            { header: 'Condition', width: 'w-20' },
            { header: 'Price', width: 'w-16' },
            { header: 'Days', width: 'w-10' },
            { header: 'Watchers', width: 'w-12' },
            { header: 'Qty', width: 'w-8' },
            { header: 'Search Rank', width: 'w-14' },
            { header: 'Active Avg', width: 'w-14' },
            { header: 'Suggested', width: 'w-14' },
          ]}
        />
      ) : listData?.items ? (
        <>
          <DataTable<ActiveListing>
            columns={[
              { key: 'sprite_url', header: '', render: (r) => r.sprite_url ? <img src={r.sprite_url as string} alt="" width={64} height={64} style={{ imageRendering: 'pixelated' }} /> : null, className: 'w-30' },
              { key: 'Title', header: 'Title', className: 'max-w-sm truncate' },
              { key: 'Condition', header: 'Condition' },
              { key: 'Price', header: 'Price', render: (r) => formatCurrency(r.Price as string) },
              { key: 'Days Listed', header: 'Days', render: (r) => formatInt(r['Days Listed'] as string) },
              { key: 'Watchers', header: 'Watchers', render: (r) => formatInt(r.Watchers as string) },
              { key: 'Quantity', header: 'Qty', render: (r) => formatInt(r.Quantity as string) },
              {
                key: 'Search Position',
                header: 'Search Rank',
                render: (r) => r['Search Position'] ? formatInt(r['Search Position'] as string) : <span className="text-slate-400 text-xs">—</span>,
              },
              {
                key: 'active_avg',
                header: 'Active Avg',
                render: (r) => {
                  const pricing = getPricingForListing(r.Card as string | null)
                  return pricing?.active_avg ? formatCurrency(pricing.active_avg) : <span className="text-slate-400 text-xs">—</span>
                },
              },
              {
                key: 'suggested',
                header: 'Suggested',
                render: (r) => {
                  const suggested = r['Suggested Price'] != null ? Number(r['Suggested Price']) : null
                  if (suggested === null) return <span className="text-slate-400 text-xs">—</span>
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
              {
                key: 'select',
                header: '',
                className: 'w-8',
                render: (r) => {
                  const suggested = r['Suggested Price'] != null ? Number(r['Suggested Price']) : null
                  const current = r.Price != null ? Number(r.Price) : null
                  const changed = suggested !== null && (current === null || Math.abs(suggested - current) >= 0.01)
                  if (!changed) return null
                  const id = r['Item ID'] as string
                  return (
                    <input
                      type="checkbox"
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
          />
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