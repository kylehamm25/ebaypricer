import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency } from '../lib/utils'
import type { PriceComparison, CardPriceDetail } from '../types'

export function PricingPage() {
  const [selectedCard, setSelectedCard] = useState<string | null>(null)

  const { data: comparisons, isLoading } = useQuery<PriceComparison[]>({
    queryKey: ['pricing-comparisons'],
    queryFn: () => api('/pricing/comparisons'),
    refetchInterval: 120_000,
  })

  const { data: cardDetail } = useQuery<CardPriceDetail>({
    queryKey: ['pricing-card', selectedCard],
    queryFn: () => api(`/pricing/cards/${encodeURIComponent(selectedCard!)}`),
    enabled: !!selectedCard,
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
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Pricing Analytics</h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          {isLoading ? (
            <TableSkeleton
              rows={8}
              columns={[
                { header: 'Card', width: 'w-48' },
                { header: 'Sold Avg', width: 'w-16' },
                { header: 'Active Avg', width: 'w-16' },
                { header: 'Spread', width: 'w-14' },
                { header: '', width: 'w-12' },
              ]}
            />
          ) : comparisons && comparisons.length > 0 ? (
            <DataTable
              columns={[
                { key: 'card_query', header: 'Card' },
                {
                  key: 'sold_weighted_avg',
                  header: 'Sold Avg',
                  render: (r) => formatCurrency(r.sold_weighted_avg as number),
                },
                {
                  key: 'active_avg',
                  header: 'Active Avg',
                  render: (r) => formatCurrency(r.active_avg as number),
                },
                {
                  key: 'spread',
                  header: 'Spread',
                  render: (r) => {
                    const v = r.spread as number | null
                    if (v == null) return '—'
                    return (
                      <span className={v > 0 ? 'text-green-600 dark:text-green-400' : v < 0 ? 'text-red-600 dark:text-red-400' : ''}>
                        {formatCurrency(v)}
                      </span>
                    )
                  },
                },
                {
                  key: 'card_query',
                  header: '',
                  render: (r) => (
                    <button
                      className="text-xs text-blue-600 hover:underline"
                      onClick={() => setSelectedCard(r.card_query as string)}
                    >
                      Details
                    </button>
                  ),
                },
              ]}
              data={comparisons as unknown as Record<string, unknown>[]}
            />
          ) : (
            <div className="text-sm text-slate-400">No price comparison data available.</div>          )}
        </div>

        {selectedCard && (
          <div className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 shadow-sm">
            <div className="flex justify-between items-center mb-3">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 truncate max-w-[200px]">
                {selectedCard}
              </h2>
              <button
                className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-neutral-300"
                onClick={() => setSelectedCard(null)}
              >
                Close
              </button>
            </div>
            {soldSnaps.length > 0 && (
              <>
                <p className="text-xs text-slate-500 mb-1">Sold Price History</p>
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={soldSnaps}>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                  <Line type="monotone" dataKey="weighted_avg" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="avg_price" stroke="#94a3b8" strokeWidth={1} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </>
            )}
            {activeSnaps.length > 0 && (
              <>
                <p className="text-xs text-slate-500 mt-3 mb-1">Active Price History</p>
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={activeSnaps}>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                  <Line type="monotone" dataKey="avg_price" stroke="#10b981" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
