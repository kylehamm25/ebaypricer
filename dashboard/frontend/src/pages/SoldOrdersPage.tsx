import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { StageRefreshButton } from '../components/shared/StageRefreshButton'
import { useChartCursor } from '../lib/theme'
import { formatCurrency, formatInt } from '../lib/utils'
import type { PaginatedResponse, SoldSummary, SoldTrend } from '../types'

// Formats a "YYYY-MM-DD" string as "Jul 10"
function formatShortDate(dateStr: string) {
  const [year, month, day] = dateStr.split('-').map(Number)
  const d = new Date(year, month - 1, day)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Computes a tick interval so at most `maxTicks` labels are shown
function getTickInterval(dataLength: number, maxTicks = 10) {
  if (dataLength <= maxTicks) return 0
  return Math.ceil(dataLength / maxTicks) - 1
}

interface SoldOrderItem extends Record<string, unknown> {
  'Item Title': string
  'Sale Date': string
  'Item Price': string
  Shipping: string
  'Total eBay Fees': string
  'Order Earnings': string
  Card?: string
  sprite_url?: string
}

export function SoldOrdersPage() {
  const cursor = useChartCursor()
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get('page') ?? '1')
  const cardFilter = searchParams.get('card') ?? ''

  // Keeps filters/page in the URL so they survive navigating away and back
  // (the page component unmounts on route change and would otherwise lose
  // plain useState).
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

  const { data: listData, isLoading } = useQuery({
    queryKey: ['sold-list', page, cardFilter],
    queryFn: () =>
      api<PaginatedResponse<SoldOrderItem>>(
        `/sold/list?page=${page}&per_page=50${cardFilter ? `&card=${encodeURIComponent(cardFilter)}` : ''}`
      ),
  })

  const { data: summary } = useQuery<SoldSummary>({
    queryKey: ['sold-summary'],
    queryFn: () => api('/sold/summary'),
  })

  const { data: trends } = useQuery<SoldTrend[]>({
    queryKey: ['sold-trends'],
    queryFn: () => api('/sold/trends?days=90'),
  })

  const totalPages = listData ? Math.ceil(listData.total / listData.per_page) : 0

  const trendData = trends ?? []
  const tickInterval = getTickInterval(trendData.length, 10)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Sold Orders</h1>
        <StageRefreshButton
          statusPath="/sold/refresh/status"
          runPath="/sold/refresh"
          label="Refresh from eBay"
          onRefreshed={() => {
            queryClient.invalidateQueries({ queryKey: ['sold-list'] })
            queryClient.invalidateQueries({ queryKey: ['sold-summary'] })
            queryClient.invalidateQueries({ queryKey: ['sold-trends'] })
          }}
        />
      </div>

      {summary ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <KpiCard title="Total Items Sold" value={formatInt(summary.total_items)} />
          <KpiCard title="Total Revenue" value={formatCurrency(summary.total_revenue)} />
          <KpiCard title="Shipping Collected" value={formatCurrency(summary.total_shipping)} />
          <KpiCard title="eBay Fees" value={formatCurrency(summary.total_fees)} />
          <KpiCard title="Order Earnings" value={formatCurrency(summary.total_earnings)} />
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
      )}

      {trends && trends.length > 0 ? (
        <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 mb-3">Daily Revenue Trend</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={trendData}>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11 }}
                interval={tickInterval}
                tickFormatter={formatShortDate}
              />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                cursor={cursor.bar}
                formatter={(v) => '$' + Number(v).toFixed(2)}
                labelFormatter={(label) => formatShortDate(label as string)}
              />
              <Bar dataKey="revenue" fill="#10b981" radius={[2, 2, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <ChartSkeleton height={240} />
      )}

      <div className="flex gap-2 items-center">
        <input
          type="text"
          placeholder="Filter by card name..."
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm w-64"
          value={cardFilter}
          onChange={(e) => updateParams({ card: e.target.value, page: null })}
        />
        <span className="text-xs text-slate-400">
          {listData ? `${listData.total} orders` : ''}
        </span>
      </div>

      {isLoading ? (
        <TableSkeleton
          rows={8}
          columns={[
            { header: '', width: 'w-10' },
            { header: 'Date', width: 'w-20' },
            { header: 'Title', width: 'w-44' },
            { header: 'Price', width: 'w-16' },
            { header: 'Shipping', width: 'w-16' },
            { header: 'Fees', width: 'w-16' },
            { header: 'Earnings', width: 'w-16' },
          ]}
        />
      ) : listData ? (
        <>
          <DataTable<SoldOrderItem>
            columns={[
              { key: 'sprite_url', header: '', render: (r) => r.sprite_url ? <img src={r.sprite_url as string} alt="" width={64} height={64} style={{ imageRendering: 'pixelated' }} /> : null, className: 'w-30' },
              { key: 'Sale Date', header: 'Date' },
              { key: 'Item Title', header: 'Title', className: 'max-w-sm truncate' },
              { key: 'Item Price', header: 'Price', render: (r) => formatCurrency(r['Item Price'] as string) },
              { key: 'Shipping', header: 'Shipping', render: (r) => formatCurrency(r['Shipping'] as string) },
              { key: 'Total eBay Fees', header: 'Fees', render: (r) => formatCurrency(r['Total eBay Fees'] as string) },
              { key: 'Order Earnings', header: 'Earnings', render: (r) => formatCurrency(r['Order Earnings'] as string) },
            ]}
            data={listData.items}
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
              Page {page} of {totalPages}
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