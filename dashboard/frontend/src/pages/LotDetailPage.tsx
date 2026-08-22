import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { LotEditDialog } from '../components/shared/LotEditDialog'
import { Money } from '../components/shared/Money'
import { KpiSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { formatCurrency, formatInt } from '../lib/utils'
import type { LotActiveRow, LotDetailResponse, LotSoldRow } from '../types'

function sprite(url: string | undefined) {
  if (!url) return null
  return <img src={url} alt="" width={48} height={48} style={{ imageRendering: 'pixelated' }} />
}

function Dash() {
  return <span className="text-slate-400 text-xs">—</span>
}

/** One buying lot: what it cost, what it has returned, and the listings behind
 *  those numbers. Reached by clicking a row on the Lots page. */
export function LotDetailPage() {
  const { sku } = useParams<{ sku: string }>()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)

  const { data, isLoading, isError, error } = useQuery<LotDetailResponse>({
    queryKey: ['lot', sku],
    queryFn: () => api(`/lots/${encodeURIComponent(sku!)}`),
    enabled: !!sku,
  })

  const lot = data?.lot
  const subtitle = [lot?.title ? lot.sku : null, lot?.source, lot?.purchased_at]
    .filter(Boolean).join(' · ')

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link
            to="/lots"
            className="inline-flex items-center gap-1 text-sm text-slate-500 dark:text-neutral-400 hover:text-slate-700 dark:hover:text-neutral-200"
          >
            <ArrowLeft size={14} /> All lots
          </Link>
          <h1 className="mt-1 text-2xl font-bold text-slate-900 dark:text-neutral-100">
            {lot?.title || lot?.sku || sku}
          </h1>
          {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
        </div>
        {lot && (
          <button
            type="button"
            className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
            onClick={() => setEditing(true)}
          >
            <Pencil size={14} /> Edit
          </button>
        )}
      </div>

      {isError && (
        <div className="rounded-lg border border-dashed border-rose-200 dark:border-rose-500/30 p-4 text-sm text-rose-600 dark:text-rose-400">
          Couldn't load this lot{error instanceof Error ? `: ${error.message}` : ''}.
        </div>
      )}

      {lot ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <KpiCard
            title="Cost"
            value={lot.cost != null ? formatCurrency(lot.cost) : '—'}
            subtitle={lot.cost == null ? 'not entered yet' : undefined}
          />
          <KpiCard
            title="Sold Net"
            value={formatCurrency(lot.sold_net)}
          />
          <KpiCard
            title="Listed Value"
            value={formatCurrency(lot.listed_value)}
          />
          <KpiCard
            title="Realized P/L"
            value={lot.realized_profit != null ? formatCurrency(lot.realized_profit) : '—'}
            tone={lot.realized_profit == null ? 'default' : lot.realized_profit >= 0 ? 'positive' : 'negative'}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
      )}

      {lot?.notes && (
        <p className="text-sm text-slate-600 dark:text-neutral-300 whitespace-pre-line">{lot.notes}</p>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200">
          Active listings{data ? <span className="text-slate-400 font-normal"> ({data.active.length})</span> : null}
        </h2>
        {isLoading ? (
          <TableSkeleton rows={4} columns={[{ header: 'Title', width: 'w-56' }, { header: 'Price', width: 'w-16' }]} />
        ) : data && data.active.length > 0 ? (
          <DataTable<LotActiveRow>
            columns={[
              { key: 'sprite_url', header: '', className: 'w-16', render: (r) => sprite(r.sprite_url) },
              {
                key: 'title',
                header: 'Title',
                className: 'max-w-sm',
                render: (r) => (
                  <div>
                    <div className="truncate text-slate-800 dark:text-neutral-100">{r.title}</div>
                    <div className="text-xs text-slate-400 truncate">
                      {[r.card, r.condition].filter(Boolean).join(' · ') || '—'}
                    </div>
                  </div>
                ),
              },
              {
                key: 'price',
                header: 'Price',
                className: 'w-24',
                render: (r) => (
                  <span className="tabular-nums">
                    {formatCurrency(r.price)}
                    {r.quantity > 1 && <span className="text-xs text-slate-400"> ×{r.quantity}</span>}
                  </span>
                ),
              },
              {
                key: 'suggested_price',
                header: 'Suggested',
                className: 'w-24',
                // Read straight from the server-computed field; never recomputed here.
                render: (r) => r.suggested_price != null
                  ? <span className="tabular-nums">{formatCurrency(r.suggested_price)}</span>
                  : <Dash />,
              },
              {
                key: 'estimated_net',
                header: 'Est. Net',
                className: 'w-24',
                render: (r) => r.estimated_net != null
                  ? <span className="tabular-nums">{formatCurrency(r.estimated_net)}</span>
                  : <Dash />,
              },
              {
                key: 'days_listed',
                header: 'Days',
                className: 'w-20',
                render: (r) => r.days_listed != null
                  ? <span className="tabular-nums text-xs">{formatInt(r.days_listed)}</span>
                  : <Dash />,
              },
              {
                key: 'watchers',
                header: 'Watch',
                className: 'w-20',
                render: (r) => r.watchers
                  ? <span className="tabular-nums text-xs">{formatInt(r.watchers)}</span>
                  : <Dash />,
              },
            ]}
            data={data.active}
            keyField="item_id"
            onRowClick={(r) => navigate(`/active/${encodeURIComponent(r.item_id)}`)}
          />
        ) : (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-sm text-slate-400">
            Nothing from this lot is listed right now.
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200">
          Sold{data ? <span className="text-slate-400 font-normal"> ({data.sold.length})</span> : null}
        </h2>
        {isLoading ? (
          <TableSkeleton rows={4} columns={[{ header: 'Title', width: 'w-56' }, { header: 'Net', width: 'w-16' }]} />
        ) : data && data.sold.length > 0 ? (
          <DataTable<LotSoldRow>
            columns={[
              { key: 'sprite_url', header: '', className: 'w-16', render: (r) => sprite(r.sprite_url) },
              {
                key: 'sale_date',
                header: 'Date',
                className: 'w-28',
                render: (r) => <span className="text-xs tabular-nums">{r.sale_date ?? '—'}</span>,
              },
              {
                key: 'item_title',
                header: 'Title',
                className: 'max-w-sm',
                render: (r) => (
                  <div>
                    <div className="truncate text-slate-800 dark:text-neutral-100">{r.item_title}</div>
                    <div className="text-xs text-slate-400 truncate">{r.card || '—'}</div>
                  </div>
                ),
              },
              {
                key: 'item_price',
                header: 'Price',
                className: 'w-24',
                render: (r) => (
                  <span className="tabular-nums">
                    {formatCurrency(r.item_price)}
                    {r.quantity > 1 && <span className="text-xs text-slate-400"> ×{r.quantity}</span>}
                  </span>
                ),
              },
              {
                key: 'line_gross',
                header: 'Gross',
                className: 'w-24',
                render: (r) => <span className="tabular-nums">{formatCurrency(r.line_gross)}</span>,
              },
              {
                key: 'line_net',
                header: 'Net',
                className: 'w-28',
                // This line's allocated share of its order's net, so a multi-item
                // order reads line by line instead of putting the whole order's
                // money on one row. Blank until eBay reports that order's fees.
                render: (r) => r.line_net != null
                  ? <Money value={r.line_net} />
                  : (
                    <span
                      className="text-xs text-slate-400"
                      title="Awaiting fee data from eBay's Finances API"
                    >
                      pending
                    </span>
                  ),
              },
            ]}
            data={data.sold}
            keyField="item_id"
          />
        ) : (
          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-sm text-slate-400">
            Nothing from this lot has sold yet.
          </div>
        )}
      </section>

      {editing && lot && <LotEditDialog lot={lot} onClose={() => setEditing(false)} />}
    </div>
  )
}
