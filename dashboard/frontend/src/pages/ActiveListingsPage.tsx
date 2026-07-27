import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { formatCurrency, formatInt } from '../lib/utils'
import type { ActiveSummary, PriceComparison, CardPriceDetail } from '../types'

interface ListingItem extends Record<string, unknown> {
  Title: string
  sprite_url?: string
  Card?: string
}

function ExpandedRowContent({ item }: { item: ListingItem }) {
  const { data: cardDetail } = useQuery<CardPriceDetail>({
    queryKey: ['pricing-card', item.Card || item.Title],
    queryFn: () => api(`/pricing/cards/${encodeURIComponent(item.Card || item.Title)}`),
    enabled: !!(item.Card || item.Title),
  })

  const soldSnaps = cardDetail?.price_snapshots?.map((s: Record<string, unknown>) => ({
    ...s,
    date: (s.snapshot_date as string)?.slice(5),
  })) ?? []

  const activeSnaps = cardDetail?.active_snapshots?.map((s: Record<string, unknown>) => ({
    ...s,
    date: (s.snapshot_date as string)?.slice(5),
  })) ?? []

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-2">
      <div className="bg-white rounded border border-slate-200 p-3">
        <p className="text-xs text-slate-500 mb-2">Sold Price History</p>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={soldSnaps}>
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => formatCurrency(Number(v))} />
            <Line type="monotone" dataKey="weighted_avg" stroke="#3b82f6" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="avg_price" stroke="#94a3b8" strokeWidth={1} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="bg-white rounded border border-slate-200 p-3">
        <p className="text-xs text-slate-500 mb-2">Active Price History</p>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={activeSnaps}>
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => formatCurrency(Number(v))} />
            <Line type="monotone" dataKey="avg_price" stroke="#10b981" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function ActiveListingsPage() {
  const [page, setPage] = useState(1)
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())

  const { data: rawList, isLoading: listLoading } = useQuery({
    queryKey: ['active-list', page],
    queryFn: () => api(`/active/list?page=${page}&per_page=50`),
  })

  const { data: summary } = useQuery<ActiveSummary>({
    queryKey: ['active-summary'],
    queryFn: () => api('/active/summary'),
  })

  const { data: comparisons } = useQuery<PriceComparison[]>({
    queryKey: ['pricing-comparisons'],
    queryFn: () => api('/pricing/comparisons'),
    refetchInterval: 120_000,
  })

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

  const toggleExpand = (key: string) => {
    const newSet = new Set(expandedRows)
    if (newSet.has(key)) {
      newSet.delete(key)
    } else {
      newSet.add(key)
    }
    setExpandedRows(newSet)
  }

  const renderExpanded = (item: ListingItem) => (
    <ExpandedRowContent item={item} />
  )

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Active Listings</h1>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div className="bg-white rounded-lg border border-slate-200 p-3">
            <p className="text-xs text-slate-500">Total Listings</p>
            <p className="text-lg font-bold">{formatInt(summary.total_listings)}</p>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-3">
            <p className="text-xs text-slate-500">Total Value</p>
            <p className="text-lg font-bold">{formatCurrency(summary.total_value)}</p>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 p-3">
            <p className="text-xs text-slate-500">Avg Days Listed</p>
            <p className="text-lg font-bold">{Math.round(summary.avg_days_listed)}d</p>
          </div>
        </div>
      )}

      {listLoading ? (
        <div className="text-sm text-slate-400">Loading...</div>
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
                key: 'pricing',
                header: 'Spread',
                render: (r) => {
                  const pricing = getPricingForListing(r.Title)
                  if (!pricing) return <span className="text-slate-400 text-xs">—</span>
                  const spread = pricing.spread
                  if (spread === null) return <span className="text-slate-400 text-xs">—</span>
                  return (
                    <span className={`text-xs font-medium ${spread > 0 ? 'text-green-600' : spread < 0 ? 'text-red-600' : ''}`}>
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
            expandedRows={expandedRows}
            onToggleExpand={toggleExpand}
            renderExpanded={renderExpanded}
          />
          <div className="flex justify-center gap-2 items-center pt-2">
            <button
              className="px-3 py-1 text-sm border rounded-md disabled:opacity-30"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <span className="text-sm text-slate-500">
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