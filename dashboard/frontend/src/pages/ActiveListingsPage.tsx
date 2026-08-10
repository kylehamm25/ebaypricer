import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { StageRefreshButton } from '../components/shared/StageRefreshButton'
import { formatCurrency, formatInt } from '../lib/utils'
import type { ActiveSummary, PriceComparison, ValueBucketResponse } from '../types'

interface ListingItem extends Record<string, unknown> {
  Title: string
  sprite_url?: string
  Card?: string
}

export function ActiveListingsPage() {
  const [page, setPage] = useState(1)
  const [cardFilter, setCardFilter] = useState('')
  const [conditionFilter, setConditionFilter] = useState('')
  const [sortBy, setSortBy] = useState('Days Listed')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const listQuery = useQuery({
    queryKey: ['active-list', page, cardFilter, conditionFilter, sortBy, sortDir],
    queryFn: () =>
      api(
        `/active/list?page=${page}&per_page=50` +
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
    setCardFilter('')
    setConditionFilter('')
    setSortBy('Days Listed')
    setSortDir('desc')
    setPage(1)
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

  const listData = rawList as { items: ListingItem[]; total: number; page: number; per_page: number } | undefined
  const totalPages = listData ? Math.ceil(listData.total / listData.per_page) : 0

  const pricingMap = new Map<string, PriceComparison>()
  comparisons?.forEach(c => pricingMap.set(c.card_query, c))

  const getPricingForListing = (title: string) => {
    if (!title) return null
    for (const [cardQuery, pricing] of pricingMap) {
      if (title.toLowerCase().includes(cardQuery.toLowerCase())) {
        return pricing
      }
    }
    const titleWords = title.toLowerCase().split(/\s+/).filter(w => w.length > 3)
    for (const [cardQuery, pricing] of pricingMap) {
      if (titleWords.some(w => cardQuery.toLowerCase().includes(w))) {
        return pricing
      }
    }
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Active Listings</h1>
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
                <Bar dataKey="count_pct" fill="#3b82f6" radius={[2, 2, 0, 0]} />
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
                <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                <Line
                  type="monotone"
                  dataKey="total_value"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={{ r: 4, fill: '#3b82f6', strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
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
          onChange={(e) => { setCardFilter(e.target.value); setPage(1) }}
        />
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={sortBy}
          onChange={(e) => { setSortBy(e.target.value); setPage(1) }}
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
          onClick={() => { setSortDir(sortDir === 'desc' ? 'asc' : 'desc'); setPage(1) }}
        >
          {sortDir === 'desc' ? '↓ Desc' : '↑ Asc'}
        </button>
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={conditionFilter}
          onChange={(e) => { setConditionFilter(e.target.value); setPage(1) }}
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
            { header: 'Spread', width: 'w-16' },
            { header: 'Sold Avg', width: 'w-14' },
            { header: 'Active Avg', width: 'w-14' },
          ]}
        />
      ) : listData?.items ? (
        <>
          <DataTable<ListingItem>
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
                key: 'pricing',
                header: 'Spread',
                render: (r) => {
                  const pricing = getPricingForListing(r.Title)
                  if (!pricing) return <span className="text-slate-400 text-xs">—</span>
                  const spread = pricing.spread
                  if (spread === null) return <span className="text-slate-400 text-xs">—</span>
                  return (
                    <span className={`text-xs font-medium ${spread > 0 ? 'text-green-600 dark:text-green-400' : spread < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>
                      {formatCurrency(spread)}
                    </span>
                  )
                },
              },
              {
                key: 'sold_avg',
                header: 'Sold Avg',
                render: (r) => {
                  const pricing = getPricingForListing(r.Title)
                  return pricing?.sold_weighted_avg ? formatCurrency(pricing.sold_weighted_avg) : <span className="text-slate-400 text-xs">—</span>
                },
              },
              {
                key: 'active_avg',
                header: 'Active Avg',
                render: (r) => {
                  const pricing = getPricingForListing(r.Title)
                  return pricing?.active_avg ? formatCurrency(pricing.active_avg) : <span className="text-slate-400 text-xs">—</span>
                },
              },
            ]}
            data={listData.items}
            keyField="Item ID"
            onRowClick={(r) => navigate(`/active/${encodeURIComponent(r['Item ID'] as string)}`)}
          />
          <div className="flex justify-center gap-2 items-center pt-2">
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
        </>
      ) : null}
    </div>
  )
}