import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { CardArt, GridShell, ViewToggle } from '../components/shared/ViewToggle'
import { GRID_CLASS, useViewPreference } from '../lib/view-preference'
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
  'Order ID': string
  'Item Title': string
  'Sale Date': string
  'Item Price': string
  Shipping: string
  'Total eBay Fees': string
  'Order Earnings': string
  Card?: string
  /** Real card art, resolved server-side from Card. Null when the order line never
   *  matched a catalog card - the sprite is the fallback. */
  card_image_url?: string | null
  sprite_url?: string
}

/** Present only for rows in a multi-item order. `first` marks the row that opens
 *  the run - it keeps its separator, the rest drop theirs. */
type GroupPos = { first: boolean }

/**
 * Marks runs of adjacent rows that belong to the same order, so the rows of one
 * multi-item order can be merged into a single block by dropping the separators
 * between them.
 *
 * Adjacency-based on purpose: the backend orders by (sale_date, order_id, ...) so
 * an order's rows arrive together, but if that ever stops holding — a different
 * sort, or an order split across a page boundary — this finds shorter runs rather
 * than merging rows that aren't actually neighbours.
 */
function groupRows(items: SoldOrderItem[]): Map<SoldOrderItem, GroupPos> {
  // Keyed by the row object rather than its index, so lookups during render are
  // O(1) instead of an indexOf scan.
  const out = new Map<SoldOrderItem, GroupPos>()
  let i = 0
  while (i < items.length) {
    const id = items[i]['Order ID']
    let end = i
    while (end + 1 < items.length && items[end + 1]['Order ID'] === id) end++
    if (end > i) {
      for (let k = i; k <= end; k++) out.set(items[k], { first: k === i })
    }
    i = end + 1
  }
  return out
}

/** Fees and earnings are reported once per ORDER, not per item, so continuation
 *  rows of a multi-item order are legitimately blank. Explain that on hover
 *  rather than showing a bare dash that reads like missing data. */
function OrderLevelCell(
  { row, field, grouped }: { row: SoldOrderItem; field: 'Total eBay Fees' | 'Order Earnings'; grouped: boolean }
) {
  const value = row[field]
  if (value != null && value !== '') return <>{formatCurrency(value as string)}</>
  return (
    <span
      className="text-slate-400 text-xs"
      title={grouped
        ? 'Counted once for the whole order — see the first row of this group'
        : 'eBay has not reported this yet'}
    >
      —
    </span>
  )
}

/** One sold line as a tile.
 *
 *  Shows the LINE's own money only - price and quantity. Fees and earnings are
 *  order-level and sit on one row of a multi-item order, so a tile is the wrong
 *  shape for them entirely: it has no neighbours to be "the first row of" and a
 *  blank on the other tiles would read as missing data. A tile from a multi-item
 *  order is badged instead, and the table is where the order-level figures live. */
function SoldCard({ item, grouped }: { item: SoldOrderItem; grouped: boolean }) {
  return (
    <GridShell>
      <div className="bg-slate-50 dark:bg-neutral-900/40">
        <CardArt artUrl={item.card_image_url} className="w-full" />
      </div>
      <div className="flex flex-col gap-1 p-2">
        <div
          className="text-sm font-medium text-slate-800 dark:text-neutral-100 truncate"
          title={item['Item Title'] as string}
        >
          {item['Item Title']}
        </div>
        <div className="text-xs text-slate-400 truncate">
          {item['Sale Date']}
          {grouped && (
            <span
              className="ml-1 text-slate-500 dark:text-neutral-400"
              title="Part of a multi-item order — fees and earnings are reported for the whole order, see the table view"
            >
              · multi-item
            </span>
          )}
        </div>
        <div className="flex items-end justify-between gap-2">
          <span className="text-sm tabular-nums text-slate-800 dark:text-neutral-100">
            {formatCurrency(item['Item Price'] as string)}
          </span>
          {Number(item.Quantity) > 1 && (
            <span className="text-xs tabular-nums text-slate-500 dark:text-neutral-400">
              ×{Number(item.Quantity)}
            </span>
          )}
        </div>
      </div>
    </GridShell>
  )
}

export function SoldOrdersPage() {
  const cursor = useChartCursor()
  const [view, chooseView] = useViewPreference('sold')
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const page = Number(searchParams.get('page') ?? '1')
  const cardFilter = searchParams.get('card') ?? ''
  // Must stay within the `le` cap on /sold/list's per_page, or the request 422s.
  const perPageOptions = [50, 100, 250, 500]
  const rawPerPage = Number(searchParams.get('per_page') ?? '50')
  const perPage = perPageOptions.includes(rawPerPage) ? rawPerPage : 50

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
    queryKey: ['sold-list', page, cardFilter, perPage],
    queryFn: () =>
      api<PaginatedResponse<SoldOrderItem>>(
        `/sold/list?page=${page}&per_page=${perPage}${cardFilter ? `&card=${encodeURIComponent(cardFilter)}` : ''}`
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

  const items = listData?.items ?? []
  const groups = groupRows(items)

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
          <KpiCard
            title="Order Earnings"
            value={formatCurrency(summary.total_earnings)}
            subtitle={
              summary.orders_missing_net > 0
                ? `${summary.orders_missing_net} order${summary.orders_missing_net === 1 ? '' : 's'} awaiting fee data`
                : undefined
            }
          />
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
        <div className="ml-auto">
          <ViewToggle view={view} onChange={chooseView} />
        </div>
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
          {view === 'grid' ? (
            items.length === 0 ? (
              <div className="bg-white dark:bg-neutral-800 rounded-xl p-8 text-center text-slate-400 text-sm">
                No data
              </div>
            ) : (
              <div className={GRID_CLASS}>
                {items.map((r) => (
                  <SoldCard
                    key={`${r['Order ID']}-${r['Item ID']}`}
                    item={r}
                    grouped={!!groups.get(r)}
                  />
                ))}
              </div>
            )
          ) : (
          <DataTable<SoldOrderItem>
            columns={[
              {
                key: 'sprite_url',
                header: '',
                className: 'w-30',
                // Real card art, sprite only as a fallback - see the Active page.
                render: (r) => (
                  <CardArt artUrl={r.card_image_url} className="w-16 rounded" />
                ),
              },
              { key: 'Sale Date', header: 'Date' },
              { key: 'Item Title', header: 'Title', className: 'max-w-sm truncate' },
              { key: 'Item Price', header: 'Price', render: (r) => formatCurrency(r['Item Price'] as string) },
              { key: 'Shipping', header: 'Shipping', render: (r) => formatCurrency(r['Shipping'] as string) },
              // Fees and earnings are order-level: eBay reports them on one row of a
              // multi-item order, so the others are genuinely blank rather than
              // missing. Say so on hover instead of leaving a bare dash.
              {
                key: 'Total eBay Fees',
                header: 'Fees',
                render: (r) => <OrderLevelCell row={r} field="Total eBay Fees" grouped={!!groups.get(r)} />,
              },
              {
                key: 'Order Earnings',
                header: 'Earnings',
                render: (r) => <OrderLevelCell row={r} field="Order Earnings" grouped={!!groups.get(r)} />,
              },
            ]}
            data={items}
            // Rows after the first in a multi-item order lose their separator, so
            // the order reads as one block. Nothing else marks them.
            hideRowDivider={(r) => {
              const g = groups.get(r)
              return !!g && !g.first
            }}
          />
          )}
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