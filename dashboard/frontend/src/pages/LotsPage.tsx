import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { LotEditDialog } from '../components/shared/LotEditDialog'
import { Money } from '../components/shared/Money'
import { KpiSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency, formatInt, profitTone } from '../lib/utils'
import type { Lot, LotsResponse } from '../types'

type SortKey = 'sku' | 'cost' | 'total_items' | 'listed_value' | 'sold_net'
  | 'realized_profit' | 'projected_profit' | 'roi_pct'

export function LotsPage() {
  const navigate = useNavigate()
  const [editing, setEditing] = useState<Lot | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>('sku')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data, isLoading, isError, error } = useQuery<LotsResponse>({
    queryKey: ['lots'],
    queryFn: () => api('/lots'),
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
            { header: 'Lot', width: 'w-40' },
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
              header: 'Lot',
              // Still sorted by SKU even when a title is showing: the codes run in
              // purchase order (L0030 before L0041), which titles won't.
              sortKey: 'sku',
              className: 'w-52',
              render: (r) => (
                <div>
                  <div className="font-medium text-slate-800 dark:text-neutral-100 truncate">
                    {r.title || r.sku}
                  </div>
                  <div className="text-xs text-slate-400 truncate">
                    {/* The SKU is the lot's identity, so it stays visible even when
                        a title has taken the main line. */}
                    {[r.title ? r.sku : null, r.source, r.purchased_at]
                      .filter(Boolean).join(' · ') || '—'}
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
              render: (r) => (
                <button
                  type="button"
                  aria-label={`Edit lot ${r.sku}`}
                  title="Edit cost and details"
                  className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                  onClick={() => setEditing(r)}
                >
                  <Pencil size={14} />
                </button>
              ),
            },
          ]}
          data={sorted}
          keyField="sku"
          sortBy={sortBy}
          sortDir={sortDir}
          onSortChange={handleSort}
          onRowClick={(r) => navigate(`/lots/${encodeURIComponent(r.sku)}`)}
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

      {editing && <LotEditDialog lot={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
