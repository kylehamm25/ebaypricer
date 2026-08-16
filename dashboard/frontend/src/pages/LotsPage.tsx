import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { api, apiPut } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { KpiSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency, formatInt } from '../lib/utils'
import type { Lot, LotsResponse } from '../types'

type SortKey = 'sku' | 'cost' | 'total_items' | 'listed_value' | 'sold_net'
  | 'realized_profit' | 'projected_profit' | 'roi_pct'

interface EditState {
  sku: string
  cost: string
  purchased_at: string
  source: string
  notes: string
}

function profitTone(v: number | null | undefined) {
  if (v == null) return 'text-slate-400'
  if (v > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (v < 0) return 'text-rose-600 dark:text-rose-400'
  return 'text-slate-500 dark:text-neutral-400'
}

function Money({ value, bold }: { value: number | null; bold?: boolean }) {
  if (value == null) return <span className="text-slate-400 text-xs">—</span>
  return (
    <span className={`tabular-nums ${bold ? 'font-semibold' : ''} ${profitTone(value)}`}>
      {value > 0 ? '+' : ''}{formatCurrency(value)}
    </span>
  )
}

export function LotsPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<EditState | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>('sku')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data, isLoading, isError, error } = useQuery<LotsResponse>({
    queryKey: ['lots'],
    queryFn: () => api('/lots'),
  })

  const saveMutation = useMutation({
    mutationFn: async (e: EditState) => {
      const cost = e.cost.trim()
      return apiPut(`/lots/${encodeURIComponent(e.sku)}`, {
        // Empty clears the value rather than saving 0 - a lot with no cost yet is
        // a different thing from a lot that cost nothing.
        cost: cost === '' ? null : Number(cost),
        purchased_at: e.purchased_at || null,
        source: e.source.trim() || null,
        notes: e.notes.trim() || null,
      })
    },
    onSuccess: () => {
      setEditing(null)
      queryClient.invalidateQueries({ queryKey: ['lots'] })
    },
  })

  const lots = useMemo(() => data?.lots ?? [], [data])

  // Only ~a dozen lots, so sorting client-side keeps header clicks instant with
  // no refetch. Nulls always sort last regardless of direction, so untracked lots
  // don't crowd out the ones with real numbers.
  const sorted = useMemo(() => {
    const rows = [...lots]
    rows.sort((a, b) => {
      const av = a[sortBy] as number | string | null
      const bv = b[sortBy] as number | string | null
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = typeof av === 'string' || typeof bv === 'string'
        ? String(av).localeCompare(String(bv))
        : (av as number) - (bv as number)
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [lots, sortBy, sortDir])

  const handleSort = (key: string) => {
    if (key === sortBy) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else { setSortBy(key as SortKey); setSortDir('desc') }
  }

  const openEdit = (lot: Lot) => setEditing({
    sku: lot.sku,
    cost: lot.cost != null ? String(lot.cost) : '',
    purchased_at: lot.purchased_at ?? '',
    source: lot.source ?? '',
    notes: lot.notes ?? '',
  })

  const totals = data?.totals

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Lots</h1>
        </div>
      </div>

      {data && !data.cost_tracking_enabled && (
        <div className="rounded-lg border border-dashed border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-300">
          Cost tracking is not set up yet — run <code className="font-mono text-xs">db/migrations/0008_lots.sql</code> in
          the Supabase SQL editor. Sales and listed values below are live; costs can't be saved until then.
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-dashed border-rose-200 dark:border-rose-500/30 p-4 text-sm text-rose-600 dark:text-rose-400">
          Couldn't load lots{error instanceof Error ? `: ${error.message}` : ''}.
        </div>
      )}

      {totals ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <KpiCard title="Invested" value={formatCurrency(totals.cost)} />
          <KpiCard title="Recouped (net)" value={formatCurrency(totals.sold_net)} />
          <KpiCard title="Realized P/L" value={formatCurrency(totals.realized_profit)} />
          <KpiCard title="Projected P/L" value={formatCurrency(totals.projected_profit)} />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
      )}

      {isLoading ? (
        <TableSkeleton
          rows={8}
          columns={[
            { header: 'SKU', width: 'w-24' },
            { header: 'Cost', width: 'w-16' },
            { header: 'Items', width: 'w-20' },
            { header: 'Listed Value', width: 'w-20' },
            { header: 'Sold Net', width: 'w-20' },
            { header: 'Realized', width: 'w-20' },
            { header: 'Projected', width: 'w-20' },
            { header: 'ROI', width: 'w-14' },
          ]}
        />
      ) : sorted.length > 0 ? (
        <DataTable<Lot>
          columns={[
            {
              key: 'sku',
              header: 'SKU',
              sortKey: 'sku',
              className: 'w-40',
              render: (r) => (
                <div>
                  <div className="font-medium text-slate-800 dark:text-neutral-100">{r.sku}</div>
                  <div className="text-xs text-slate-400 truncate">
                    {[r.source, r.purchased_at].filter(Boolean).join(' · ') || '—'}
                  </div>
                </div>
              ),
            },
            {
              key: 'cost',
              header: 'Cost',
              sortKey: 'cost',
              className: 'w-24',
              render: (r) => r.cost != null
                ? <span className="tabular-nums">{formatCurrency(r.cost)}</span>
                : <span className="text-slate-400 text-xs">not set</span>,
            },
            {
              key: 'total_items',
              header: 'Items',
              sortKey: 'total_items',
              className: 'w-28',
              render: (r) => (
                <span className="text-xs tabular-nums text-slate-600 dark:text-neutral-300">
                  {formatInt(r.sold_items)} sold
                  <span className="text-slate-300 dark:text-neutral-600"> / </span>
                  {formatInt(r.active_items)} live
                </span>
              ),
            },
            {
              key: 'listed_value',
              header: 'Listed Value',
              sortKey: 'listed_value',
              className: 'w-28',
              render: (r) => <span className="tabular-nums">{formatCurrency(r.listed_value)}</span>,
            },
            {
              key: 'sold_net',
              header: 'Sold Net',
              sortKey: 'sold_net',
              className: 'w-28',
              render: (r) => (
                <span
                  className="tabular-nums"
                  title={`${formatCurrency(r.sold_gross)} gross before fees${
                    r.sold_missing_net ? ` · ${r.sold_missing_net} sale(s) still awaiting fee data` : ''
                  }`}
                >
                  {formatCurrency(r.sold_net)}
                  {r.sold_missing_net > 0 && <span className="ml-1 text-slate-400">*</span>}
                </span>
              ),
            },
            {
              key: 'recouped',
              header: 'Recouped',
              className: 'w-28',
              render: (r) => {
                if (r.recouped_pct == null) return <span className="text-slate-400 text-xs">—</span>
                const pct = Math.max(0, Math.min(100, r.recouped_pct))
                const done = r.recouped_pct >= 100
                return (
                  <div className="flex items-center gap-2" title={`${r.recouped_pct}% of cost recovered from sales`}>
                    <div className="h-1.5 w-12 rounded-full bg-slate-200 dark:bg-neutral-700 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${done ? 'bg-emerald-500' : 'bg-blue-500'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-slate-500 dark:text-neutral-400">
                      {Math.round(r.recouped_pct)}%
                    </span>
                  </div>
                )
              },
            },
            {
              key: 'realized_profit',
              header: 'Realized',
              sortKey: 'realized_profit',
              className: 'w-24',
              render: (r) => <Money value={r.realized_profit} bold />,
            },
            {
              key: 'projected_profit',
              header: 'Projected',
              sortKey: 'projected_profit',
              className: 'w-24',
              render: (r) => <Money value={r.projected_profit} />,
            },
            {
              key: 'roi_pct',
              header: 'ROI',
              sortKey: 'roi_pct',
              className: 'w-20',
              render: (r) => r.roi_pct == null
                ? <span className="text-slate-400 text-xs">—</span>
                : <span className={`tabular-nums text-xs font-medium ${profitTone(r.roi_pct)}`}>
                    {r.roi_pct > 0 ? '+' : ''}{r.roi_pct}%
                  </span>,
            },
            {
              key: 'edit',
              header: '',
              className: 'w-12',
              stopRowClick: true,
            },
          ]}
          data={sorted}
          keyField="sku"
          sortBy={sortBy}
          sortDir={sortDir}
          onSortChange={handleSort}
          onRowClick={openEdit}
        />
      ) : !isError ? (
        <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-sm text-slate-400">
          No purchased lots found on your listings or orders yet.
        </div>
      ) : null}

      {sorted.some((r) => r.sold_missing_net > 0) && (
        <p className="text-xs text-slate-400 dark:text-neutral-500">
          * Some sales don't have eBay fee data yet, so their net isn't counted. It fills in once the Finances API reports them.
        </p>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 w-full max-w-md">
            <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100 mb-1">
              Lot {editing.sku}
            </h2>
            <p className="text-xs text-slate-500 dark:text-neutral-400 mb-4">
              What you paid for the whole lot, not per card.
            </p>

            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Cost paid</span>
                <div className="relative mt-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    autoFocus
                    className="w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg pl-7 pr-3 py-1.5 text-sm tabular-nums"
                    value={editing.cost}
                    placeholder="Leave blank if unknown"
                    onChange={(e) => setEditing({ ...editing, cost: e.target.value })}
                  />
                </div>
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Purchased</span>
                <input
                  type="date"
                  className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm"
                  value={editing.purchased_at}
                  onChange={(e) => setEditing({ ...editing, purchased_at: e.target.value })}
                />
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Source</span>
                <input
                  type="text"
                  className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm"
                  value={editing.source}
                  placeholder="Where you bought it"
                  onChange={(e) => setEditing({ ...editing, source: e.target.value })}
                />
              </label>

              <label className="block">
                <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Notes</span>
                <textarea
                  rows={2}
                  className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm resize-none"
                  value={editing.notes}
                  onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
                />
              </label>
            </div>

            {saveMutation.isError && (
              <p className="text-xs text-rose-600 dark:text-rose-400 mt-3">
                {(saveMutation.error as Error).message}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-4">
              <button
                className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
                onClick={() => { saveMutation.reset(); setEditing(null) }}
                disabled={saveMutation.isPending}
              >
                Cancel
              </button>
              <button
                className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
                onClick={() => saveMutation.mutate(editing)}
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
