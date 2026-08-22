import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { apiPut } from '../../lib/api'
import type { Lot } from '../../types'

interface EditState {
  title: string
  cost: string
  purchased_at: string
  source: string
  notes: string
}

/** The lot cost/details editor, shared by the lots list and a lot's own page so
 *  both save through one code path. */
export function LotEditDialog({ lot, onClose }: { lot: Lot; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<EditState>({
    title: lot.title ?? '',
    cost: lot.cost != null ? String(lot.cost) : '',
    purchased_at: lot.purchased_at ?? '',
    source: lot.source ?? '',
    notes: lot.notes ?? '',
  })

  const saveMutation = useMutation({
    mutationFn: async (e: EditState) => {
      const cost = e.cost.trim()
      return apiPut(`/lots/${encodeURIComponent(lot.sku)}`, {
        title: e.title.trim() || null,
        // Empty clears the value rather than saving 0 - a lot with no cost yet is
        // a different thing from a lot that cost nothing.
        cost: cost === '' ? null : Number(cost),
        purchased_at: e.purchased_at || null,
        source: e.source.trim() || null,
        notes: e.notes.trim() || null,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lots'] })
      queryClient.invalidateQueries({ queryKey: ['lot', lot.sku] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 w-full max-w-md">
        <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100 mb-1">
          Lot {lot.sku}
        </h2>
        <p className="text-xs text-slate-500 dark:text-neutral-400 mb-4">
          Cost is what you paid for the whole lot, not per card.
        </p>

        <div className="space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Title</span>
            <input
              type="text"
              autoFocus
              maxLength={200}
              className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm"
              value={form.title}
              placeholder="What this lot was, e.g. Estate collection, 2500 bulk"
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Cost paid</span>
            <div className="relative mt-1">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
              <input
                type="number"
                step="0.01"
                min="0"
                className="w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg pl-7 pr-3 py-1.5 text-sm tabular-nums"
                value={form.cost}
                placeholder="Leave blank if unknown"
                onChange={(e) => setForm({ ...form, cost: e.target.value })}
              />
            </div>
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Purchased</span>
            <input
              type="date"
              className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm"
              value={form.purchased_at}
              onChange={(e) => setForm({ ...form, purchased_at: e.target.value })}
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Source</span>
            <input
              type="text"
              className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm"
              value={form.source}
              placeholder="Where you bought it"
              onChange={(e) => setForm({ ...form, source: e.target.value })}
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Notes</span>
            <textarea
              rows={2}
              className="mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm resize-none"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
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
            onClick={onClose}
            disabled={saveMutation.isPending}
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            onClick={() => saveMutation.mutate(form)}
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
