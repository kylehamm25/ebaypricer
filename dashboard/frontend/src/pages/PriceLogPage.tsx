import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { TrendingDown, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency } from '../lib/utils'
import type { PriceChangeEntry, PriceChangesResponse } from '../types'

const DAY_OPTIONS = [7, 30, 90, 365]

const SOURCE_LABELS: Record<string, string> = {
  single: 'Single',
  bulk: 'Bulk',
}

function formatDateTime(v: string) {
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

export function PriceLogPage() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)
  const [source, setSource] = useState<'' | 'single' | 'bulk'>('')
  const [search, setSearch] = useState('')

  const { data, isLoading, isError, error } = useQuery<PriceChangesResponse>({
    queryKey: ['price-changes', days],
    queryFn: () => api(`/active/price-changes?days=${days}&limit=1000`),
  })

  const changes = useMemo(() => data?.changes ?? [], [data])

  const filtered = useMemo(() => {
    let rows = changes
    if (source) rows = rows.filter((r) => r.source === source)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      rows = rows.filter(
        (r) => (r.title ?? '').toLowerCase().includes(q) || (r.card ?? '').toLowerCase().includes(q)
      )
    }
    return rows
  }, [changes, source, search])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Price Log</h1>
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {DAY_OPTIONS.map((d) => (
            <option key={d} value={d}>Last {d} days</option>
          ))}
        </select>
      </div>

      {isError && (
        <div className="rounded-lg border border-dashed border-rose-200 dark:border-rose-500/30 p-4 text-sm text-rose-600 dark:text-rose-400">
          Couldn't load the price log{error instanceof Error ? `: ${error.message}` : ''}.
        </div>
      )}

      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          placeholder="Filter by title or card..."
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm w-64"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="border border-slate-300 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 rounded-lg px-2 py-1.5 text-sm bg-white"
          value={source}
          onChange={(e) => setSource(e.target.value as '' | 'single' | 'bulk')}
        >
          <option value="">All Sources</option>
          <option value="single">Single</option>
          <option value="bulk">Bulk</option>
        </select>
        <span className="text-xs text-slate-400">
          {data ? `${filtered.length} of ${changes.length} changes` : ''}
        </span>
      </div>

      {isLoading ? (
        <TableSkeleton
          rows={8}
          columns={[
            { header: 'Date', width: 'w-24' },
            { header: 'Title', width: 'w-56' },
            { header: 'Price Change', width: 'w-32' },
            { header: 'Source', width: 'w-16' },
          ]}
        />
      ) : filtered.length > 0 ? (
        <DataTable<PriceChangeEntry>
          columns={[
            { key: 'changed_at', header: 'Date', className: 'w-32', render: (r) => formatDateTime(r.changed_at) },
            {
              key: 'title',
              header: 'Listing',
              className: 'max-w-sm',
              render: (r) => (
                <div>
                  <div className="truncate font-medium text-slate-800 dark:text-neutral-100">
                    {r.title || <span className="text-slate-400 italic">Listing ended</span>}
                  </div>
                  {r.card && <div className="text-xs text-slate-400 truncate">{r.card}</div>}
                </div>
              ),
            },
            {
              key: 'change',
              header: 'Price Change',
              className: 'w-40',
              render: (r) => {
                const delta = r.old_price != null ? r.new_price - r.old_price : null
                const up = delta !== null && delta > 0
                const down = delta !== null && delta < 0
                return (
                  <div className="flex items-center gap-1.5">
                    <span className="tabular-nums text-slate-500 dark:text-neutral-400">
                      {r.old_price != null ? formatCurrency(r.old_price) : '—'}
                    </span>
                    <span className="text-slate-300 dark:text-neutral-600">→</span>
                    <span className="tabular-nums font-semibold text-slate-800 dark:text-neutral-100">
                      {formatCurrency(r.new_price)}
                    </span>
                    {up && <TrendingUp size={13} className="text-amber-500 dark:text-amber-400" />}
                    {down && <TrendingDown size={13} className="text-emerald-500 dark:text-emerald-400" />}
                  </div>
                )
              },
            },
            {
              key: 'source',
              header: 'Source',
              className: 'w-20',
              render: (r) => (
                <span className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 dark:bg-neutral-700 dark:text-neutral-300 ring-1 ring-inset ring-slate-500/10">
                  {SOURCE_LABELS[r.source] ?? r.source}
                </span>
              ),
            },
          ]}
          data={filtered}
          onRowClick={(r) => navigate(`/active/${encodeURIComponent(r.item_id)}`)}
          hideHeader
        />
      ) : !isError ? (
        <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-sm text-slate-400">
          No price changes in this window.
        </div>
      ) : null}
    </div>
  )
}
