import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { apiPost } from '../../lib/api'
import type { LotOption } from '../../types'

// Same vocabulary as CONDITION_MULTIPLIER in services/suggested_price.py.
const CONDITIONS = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged']

// Distinct from '' (leave unchanged) so the select can offer clearing, which a
// blank text box can't express. Never sent as-is - it becomes an explicit null.
const CLEAR = '__clear__'

const FIELD =
  'mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 ' +
  'dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm'

const LABEL = 'text-xs font-medium text-slate-600 dark:text-neutral-300'

/** Edit what a whole stack of cards has in common: where it lives, which lot it
 *  came from, what grade it is. Prices are per-card judgements and are deliberately
 *  not offered here.
 *
 *  Anything left blank is left alone - only filled-in fields are sent, so the
 *  backend never receives a key for them. Clearing a location or lot in bulk is
 *  deliberately not offered: a blank box already means "leave alone", and one
 *  control cannot mean both. Condition can be cleared, because a select has room
 *  to say so outright. */
export function InventoryBulkDialog({ ids, locations, skus, onClose }: {
  ids: number[]
  locations: string[]
  skus: LotOption[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [location, setLocation] = useState('')
  const [sku, setSku] = useState('')
  const [condition, setCondition] = useState('')

  const body: Record<string, unknown> = { ids }
  if (location.trim()) body.location = location.trim()
  if (sku.trim()) body.sku = sku.trim()
  if (condition) body.condition = condition === CLEAR ? null : condition

  // ids is always present, so anything beyond it is a real change.
  const changeCount = Object.keys(body).length - 1

  const save = useMutation({
    mutationFn: () => apiPost('/inventory/bulk-update', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 w-full max-w-md">
        <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100 mb-1">
          Edit {ids.length} {ids.length === 1 ? 'item' : 'items'}
        </h2>
        <p className="text-xs text-slate-500 dark:text-neutral-400 mb-4">
          Anything left blank stays as it is.
        </p>

        <div className="space-y-3">
          <label className="block">
            <span className={LABEL}>Location</span>
            <input
              type="text"
              autoFocus
              maxLength={120}
              list="inventory-bulk-locations"
              className={FIELD}
              value={location}
              placeholder="Box 3 / Binder A p.12"
              onChange={(e) => setLocation(e.target.value)}
            />
            <datalist id="inventory-bulk-locations">
              {locations.map((l) => <option key={l} value={l} />)}
            </datalist>
          </label>

          <label className="block">
            <span className={LABEL}>Lot SKU</span>
            <input
              type="text"
              maxLength={40}
              list="inventory-bulk-skus"
              className={FIELD}
              value={sku}
              placeholder="L0042"
              onChange={(e) => setSku(e.target.value)}
            />
            <datalist id="inventory-bulk-skus">
              {skus.map((l) => <option key={l.sku} value={l.sku}>{l.title || undefined}</option>)}
            </datalist>
          </label>

          <label className="block">
            <span className={LABEL}>Condition</span>
            <select
              className={FIELD}
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
            >
              <option value="">Leave unchanged</option>
              {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
              <option value={CLEAR}>Clear condition</option>
            </select>
          </label>
        </div>

        {save.isError && (
          <p className="text-xs text-rose-600 dark:text-rose-400 mt-3">
            {(save.error as Error).message}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-4">
          <button
            className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
            onClick={onClose}
            disabled={save.isPending}
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            onClick={() => save.mutate()}
            disabled={save.isPending || changeCount === 0}
          >
            {save.isPending && <Loader2 size={14} className="animate-spin" />}
            Apply to {ids.length}
          </button>
        </div>
      </div>
    </div>
  )
}
