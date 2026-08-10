import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'
import {
  ArrowLeft,
  ExternalLink,
  ImageIcon,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency, formatInt } from '../lib/utils'
import type { CardPriceDetail } from '../types'

interface ListingItem extends Record<string, unknown> {
  'Item ID': string
  Title: string
  Card?: string
  Condition?: string
  Price?: string
  sprite_url?: string
}

const CONDITION_STYLES: Record<string, string> = {
  new: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 ring-1 ring-inset ring-emerald-600/20',
  'like new': 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 ring-1 ring-inset ring-emerald-600/20',
  'near mint': 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 ring-1 ring-inset ring-emerald-600/20',
  'lightly played': 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 ring-1 ring-inset ring-amber-600/20',
  used: 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 ring-1 ring-inset ring-amber-600/20',
  good: 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 ring-1 ring-inset ring-amber-600/20',
  played: 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300 ring-1 ring-inset ring-rose-600/20',
  damaged: 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300 ring-1 ring-inset ring-rose-600/20',
  poor: 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300 ring-1 ring-inset ring-rose-600/20',
}

function conditionClass(condition?: string) {
  if (!condition) return 'bg-slate-100 text-slate-600 dark:bg-neutral-700 dark:text-neutral-300 ring-1 ring-inset ring-slate-500/10'
  return (
    CONDITION_STYLES[condition.toLowerCase()] ??
    'bg-slate-100 text-slate-600 dark:bg-neutral-700 dark:text-neutral-300 ring-1 ring-inset ring-slate-500/10'
  )
}

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(String(v).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(n) ? n : null
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-[200px] flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-slate-400">
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function ListingDetailPage() {
  const { itemId } = useParams<{ itemId: string }>()

  const { data: item, isLoading } = useQuery<ListingItem | null>({
    queryKey: ['active-item', itemId],
    queryFn: () => api(`/active/item/${encodeURIComponent(itemId!)}`),
    enabled: !!itemId,
  })

  const cardQuery = item?.Card || item?.Title || ''
  const { data: cardDetail, isLoading: cardLoading } = useQuery<CardPriceDetail>({
    queryKey: ['pricing-card', cardQuery],
    queryFn: () => api(`/pricing/cards/${encodeURIComponent(cardQuery)}`),
    enabled: !!cardQuery,
  })

  const soldSnaps: Record<string, unknown>[] = (cardDetail?.price_snapshots ?? []).map((s) => ({
    ...s,
    date: (s.snapshot_date as string)?.slice(5),
  })).reverse()

  const activeSnaps: Record<string, unknown>[] = (cardDetail?.active_snapshots ?? []).map((s) => ({
    ...s,
    date: (s.snapshot_date as string)?.slice(5),
  })).reverse()

  const priceHistory: { date: string; sold?: number; active?: number }[] = []
  for (const s of soldSnaps) {
    const row = { date: s.date as string, sold: Number(s.avg_price) }
    priceHistory.push(row)
  }
  for (const a of activeSnaps) {
    const row = priceHistory.find((r) => r.date === (a.date as string))
    if (row) row.active = Number(a.avg_price)
    else priceHistory.push({ date: a.date as string, active: Number(a.avg_price) })
  }
  priceHistory.sort((a, b) => a.date.localeCompare(b.date))

  const recentSold = cardDetail?.recent_sold ?? []
  const matchedNote = cardDetail?.matched_query ? `Showing data for: ${cardDetail.card_query}` : null

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonHeader />
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-7 gap-4">
          {Array.from({ length: 7 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartSkeleton height={200} />
          <ChartSkeleton height={200} />
        </div>
        <TableSkeleton rows={5} columns={[{ header: 'Title', width: 'w-72' }, { header: 'Price', width: 'w-16' }]} />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="space-y-4">
        <Link to="/active" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} /> Back to Active Listings
        </Link>
        <div className="text-sm text-slate-400">Listing not found.</div>
      </div>
    )
  }

  const money = (v: unknown) => (v !== null && v !== undefined && v !== '' ? formatCurrency(v as string) : '—')
  const int = (v: unknown) => (v !== null && v !== undefined && v !== '' ? formatInt(v as string) : '—')
  const pct = (v: unknown) => {
    if (v === null || v === undefined || v === '') return '—'
    const s = String(v)
    return s.includes('%') ? s : `${s}%`
  }

  const priceNum = toNumber(item.Price)
  const soldAvgNum = toNumber(item['Recent Sold Avg'])
  const deltaPct =
    priceNum !== null && soldAvgNum !== null && soldAvgNum !== 0
      ? ((priceNum - soldAvgNum) / soldAvgNum) * 100
      : null
  const deltaVsSold = priceNum !== null && soldAvgNum !== null ? priceNum - soldAvgNum : null

  const soldPrices = recentSold
    .map((r) => Number(r.price))
    .filter((n) => Number.isFinite(n))
  const soldMin = soldPrices.length ? Math.min(...soldPrices) : null
  const soldMax = soldPrices.length ? Math.max(...soldPrices) : null
  const soldAvg =
    soldPrices.length ? soldPrices.reduce((a, b) => a + b, 0) / soldPrices.length : null

  const ebayUrl = `https://www.ebay.com/itm/${String(item['Item ID']).replace(/[^0-9]/g, '')}`

  const rankNum = toNumber(item['Search Position'])
  const watchersNum = toNumber(item.Watchers)

  return (
    <div className="space-y-8">
      <Link
        to="/active"
        className="group inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline"
      >
        <ArrowLeft size={14} className="transition-transform group-hover:-translate-x-0.5" />
        Back to Active Listings
      </Link>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Header */}
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex flex-col justify-between">
        <div className="flex flex-wrap items-start gap-5">
          {item.sprite_url ? (
            <img
              src={item.sprite_url as string}
              alt=""
              width={96}
              height={96}
              style={{ imageRendering: 'pixelated' }}
              className="shrink-0"
            />
          ) : (
            <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-lg bg-slate-50 dark:bg-neutral-700/50 ring-1 ring-slate-200 dark:ring-neutral-600">
              <ImageIcon size={28} className="text-slate-300 dark:text-neutral-500" />
            </div>
          )}

          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100 leading-snug tracking-tight">
              {item.Title}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {item.Condition && (
                <span className={`px-2 py-0.5 rounded-md text-xs font-medium ${conditionClass(item.Condition)}`}>
                  {item.Condition}
                </span>
              )}
              {item.Card && <span className="text-slate-500 dark:text-neutral-400 text-xs">{item.Card}</span>}
            </div>
          </div>

          <div className="flex flex-col items-end gap-1.5 pl-4 border-l border-slate-100 dark:border-neutral-700">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Price</p>
            <p className="text-3xl font-bold text-slate-900 dark:text-neutral-100 tabular-nums">{money(item.Price)}</p>
            {deltaPct !== null && (
              <span
                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${
                  deltaPct <= 0
                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                    : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'
                }`}
              >
                {deltaPct <= 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
                {Math.abs(deltaPct).toFixed(1)}% {deltaPct <= 0 ? 'below' : 'above'} sold avg
              </span>
            )}
            <div className="mt-1 text-right text-xs text-slate-500 dark:text-neutral-400">
              Est. Net{' '}
              <span className="font-semibold text-slate-700 dark:text-neutral-200 tabular-nums">{money(item['Estimated Net'])}</span>
              {' · '}
              Est. Fees{' '}
              <span className="font-semibold text-slate-700 dark:text-neutral-200 tabular-nums">{money(item['Estimated Fees'])}</span>
            </div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-4 gap-y-3 border-t border-slate-100 dark:border-neutral-700 pt-4 text-sm justify-items-start">
          <div>
            <a
              href={ebayUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 dark:text-blue-400 font-medium hover:underline inline-flex items-center gap-1 text-sm"
            >
              View on eBay
              <ExternalLink size={11} />
            </a>
          </div>
          <div>
            <p className="text-xs text-slate-400">Start Date</p>
            <p className="text-slate-700 dark:text-neutral-200 font-medium">{(item['Start Date'] as string) || '—'}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Watchers</p>
            <p className={`text-slate-700 dark:text-neutral-200 font-medium ${watchersNum === 1 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
              {watchersNum}
            </p>
          </div>
          {toNumber(item.Quantity) !== null && toNumber(item.Quantity)! > 1 && (
            <div>
              <p className="text-xs text-slate-400">Quantity</p>
              <p className="text-slate-700 dark:text-neutral-200 font-medium">{int(item.Quantity)}</p>
            </div>
          )}
          <div>
            <p className="text-xs text-slate-400">Ad Rate</p>
            <p className="text-slate-700 dark:text-neutral-200 font-medium">{pct(item['Ad Rate'])}</p>
          </div>
          {rankNum !== null && (
            <div>
              <p className="text-xs text-slate-400">Search Rank</p>
              <p className="text-slate-700 dark:text-neutral-200 font-medium">#{rankNum}</p>
            </div>
          )}
        </div>
      </div>

      {/* Price history */}
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200">Price History</h2>
          {priceHistory.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 justify-end">
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-neutral-400">
                <span className="h-2 w-2 rounded-full bg-blue-500" /> Sold avg
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-neutral-400">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> Active avg
              </span>
              {priceNum !== null && (
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-neutral-400">
                  <span className="h-0.5 w-3 border-t-2 border-dashed border-amber-500" /> Listed price
                </span>
              )}
            </div>
          )}
        </div>
        {matchedNote && <p className="text-xs text-slate-400 mb-2">{matchedNote}</p>}
        {cardLoading ? (
          <ChartSkeleton height={220} />
        ) : priceHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={priceHistory}>
              <CartesianGrid vertical={false} stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
              <Tooltip formatter={(v, name) => [
                formatCurrency(Number(v)),
                name === 'sold' ? 'Sold avg' : 'Active avg',
              ]} />
              {priceNum !== null && (
                <ReferenceLine
                  y={priceNum}
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                  label={{ value: `Listed $${priceNum.toFixed(2)}`, position: 'insideTopLeft', fill: '#b45309', fontSize: 10 }}
                />
              )}
              <Line type="monotone" dataKey="sold" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls />
              <Line type="monotone" dataKey="active" stroke="#10b981" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <EmptyChart label="No price history." />
        )}
      </div>
      </div>

      {/* Recent sold listings */}
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 mb-1">Recent Sold Listings</h2>
        {matchedNote && <p className="text-xs text-slate-400 mb-3">{matchedNote}</p>}
        {cardLoading ? (
          <TableSkeleton rows={5} columns={[{ header: 'Title', width: 'w-72' }, { header: 'Price', width: 'w-16' }]} />
        ) : recentSold.length > 0 ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
              <div className="rounded-lg bg-slate-50 dark:bg-neutral-700/50 px-3 py-2">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-medium">Sold Count</p>
                <p className="text-lg font-bold text-slate-900 dark:text-neutral-100 tabular-nums">
                  {int(item['Recent Sold Count'])}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-neutral-700/50 px-3 py-2">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-medium">Sold Avg</p>
                <p className="text-lg font-bold text-slate-900 dark:text-neutral-100 tabular-nums">
                  {soldAvg !== null ? formatCurrency(soldAvg) : '—'}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-neutral-700/50 px-3 py-2">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-medium">Sold Min</p>
                <p className="text-lg font-bold text-slate-900 dark:text-neutral-100 tabular-nums">
                  {soldMin !== null ? formatCurrency(soldMin) : '—'}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-neutral-700/50 px-3 py-2">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-medium">Sold Max</p>
                <p className="text-lg font-bold text-slate-900 dark:text-neutral-100 tabular-nums">
                  {soldMax !== null ? formatCurrency(soldMax) : '—'}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-neutral-700/50 px-3 py-2">
                <p className="text-[11px] text-slate-400 uppercase tracking-wide font-medium">Vs Sold Avg</p>
                <p className={`text-lg font-bold tabular-nums ${deltaVsSold === null || deltaVsSold === 0 ? 'text-slate-900 dark:text-neutral-100' : deltaVsSold < 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                  {deltaVsSold !== null ? formatCurrency(deltaVsSold) : '—'}
                </p>
              </div>
            </div>
            <DataTable
              columns={[
                { key: 'sold_date', header: 'Sold Date' },
                { key: 'title', header: 'Title', className: 'max-w-sm truncate' },
                { key: 'price', header: 'Price', render: (r) => formatCurrency(r.price as string) },
                { key: 'condition', header: 'Condition' },
                { key: 'listing_type', header: 'Type' },
              ]}
              data={recentSold as Record<string, unknown>[]}
            />
          </>
        ) : (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-sm text-slate-400">
            No recent sold listings.
          </div>
        )}
      </div>
    </div>
  )
}

function SkeletonHeader() {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex items-start gap-5">
      <div className="w-24 h-24 rounded-lg bg-slate-200 dark:bg-neutral-700 animate-pulse shrink-0" />
      <div className="space-y-2 w-full">
        <div className="h-6 w-3/4 bg-slate-200 dark:bg-neutral-700 animate-pulse rounded-md" />
        <div className="h-4 w-40 bg-slate-200 dark:bg-neutral-700 animate-pulse rounded-md" />
      </div>
    </div>
  )
}