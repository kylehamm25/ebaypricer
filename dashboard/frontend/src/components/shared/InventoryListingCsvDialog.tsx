import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Download, Loader2 } from 'lucide-react'
import { apiPost } from '../../lib/api'
import { formatCurrency } from '../../lib/utils'
import type { ListingCsvMode, ListingCsvResponse } from '../../types'

/** Hands the built file to the browser, in whichever form the server produced.
 *
 *  Nothing crosses the network twice - the table shown above and the file downloaded
 *  here came from the same response. */
function download(result: ListingCsvResponse) {
  // No BOM: the Action header declares CC=UTF-8, so eBay reads the bytes as UTF-8
  // already, and a BOM ahead of the '#INFO' line risks that first line no longer
  // looking like a comment. Excel is the loser there, not eBay, and eBay is who has to
  // accept the file.
  const url = URL.createObjectURL(new Blob([result.csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = result.filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Turn selected inventory rows into one of eBay's bulk-upload files.
 *
 *  Builds on open and asks nothing. Everything the file needs beyond the rows - the
 *  item location and the three business policy names - is the same on every export
 *  forever, so it lives on the Settings page; a user who hasn't filled it in gets the
 *  backend's message and a link there rather than a form to fill in twice.
 *
 *  It still shows what it built before handing it over. Every line becomes a live
 *  listing at a price this app chose, and preview-then-confirm is the house style for
 *  anything ending in a marketplace write (see the ebay-listing-dry-run skill) - even
 *  one the seller uploads themselves. The rows left out matter just as much as the
 *  ones in: a card nothing has priced silently missing from the file is how you
 *  discover it three weeks later, still in the box.
 *
 *  Nothing here computes a price or a title. Both arrive from services/listing_csv.py
 *  already decided, for the same reason the list and detail pages both read one
 *  server-side suggested price. */
export function InventoryListingCsvDialog({ ids, onClose }: {
  ids: number[]
  onClose: () => void
}) {
  // Drafts by default: they need nothing set up, they are reversible, and finishing
  // one in eBay's listing tool is a smaller commitment than a listing that is already
  // live. Creating outright is the deliberate choice, not the default.
  const [mode, setMode] = useState<ListingCsvMode>('draft')

  const build = useMutation({
    mutationFn: (m: ListingCsvMode) =>
      apiPost('/inventory/listing-csv', { ids, mode: m }) as Promise<ListingCsvResponse>,
  })

  // Rebuilt whenever the mode changes. `ids` is a fresh array each render, so it
  // deliberately isn't a dependency - the dialog is unmounted and remounted to
  // export a different selection.
  const run = build.mutate
  useEffect(() => { run(mode) }, [run, mode])

  const result = build.data

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="p-5 pb-3">
          <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100">
            Listing file for {ids.length} {ids.length === 1 ? 'item' : 'items'}
          </h2>
        </div>

        <div className="px-5 pb-5 overflow-y-auto space-y-4">
          {/* eBay takes two different files here, and which one you want depends on
              whether these are going live now or being finished by hand. */}
          <div className="flex gap-2">
            {(['draft', 'add'] as ListingCsvMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1.5 text-sm rounded-lg border ${
                  mode === m
                    ? 'border-blue-600 bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-300'
                    : 'border-slate-300 dark:border-neutral-600 text-slate-700 dark:text-neutral-200'
                }`}
              >
                {m === 'draft' ? 'Create drafts' : 'List immediately'}
              </button>
            ))}
          </div>

          <p className="text-xs text-slate-500 dark:text-neutral-400">
            {mode === 'draft'
              ? 'Rows land in eBay’s drafts, where you set shipping, returns and payment before publishing.'
              : 'Rows become live listings, using the business policies from Settings.'}
          </p>
          {build.isPending && (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-neutral-400">
              <Loader2 size={16} className="animate-spin" /> Building...
            </div>
          )}

          {build.isError && (
            <div className="space-y-2">
              <p className="text-sm text-rose-600 dark:text-rose-400">
                {(build.error as Error).message}
              </p>
              <Link
                to="/settings"
                onClick={onClose}
                className="inline-block text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                Open Settings
              </Link>
            </div>
          )}

          {result && (
            <>
              {result.drafts.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-slate-500 dark:text-neutral-400">
                        <th className="py-1 pr-3 font-medium">Title</th>
                        <th className="py-1 pr-3 font-medium w-12">Qty</th>
                        <th className="py-1 font-medium w-24 text-right">Price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.drafts.map((d) => (
                        <tr key={d.id} className="border-t border-slate-100 dark:border-neutral-700 align-top">
                          <td className="py-1.5 pr-3">
                            <div className="text-slate-800 dark:text-neutral-100">{d.title}</div>
                            {d.warnings.map((w) => (
                              <div key={w} className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                                {w}
                              </div>
                            ))}
                          </td>
                          <td className="py-1.5 pr-3 tabular-nums text-slate-600 dark:text-neutral-300">
                            {d.quantity}
                          </td>
                          <td className="py-1.5 tabular-nums text-right text-slate-800 dark:text-neutral-100">
                            {formatCurrency(d.price)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {result.skipped.length > 0 && (
                <div className="rounded-lg bg-slate-50 dark:bg-neutral-900/50 p-3">
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-600 dark:text-neutral-300">
                    <AlertTriangle size={13} className="text-amber-500" />
                    Left out of the file ({result.skipped.length})
                  </div>
                  <ul className="mt-1.5 space-y-0.5">
                    {result.skipped.map((s) => (
                      <li key={s.id} className="text-xs text-slate-500 dark:text-neutral-400">
                        <span className="text-slate-700 dark:text-neutral-200">{s.name}</span>
                        {' — '}{s.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.drafts.length === 0 && (
                <p className="text-sm text-slate-600 dark:text-neutral-300">
                  Nothing in this selection can be listed yet.
                </p>
              )}

              {/* Said here rather than on Settings: this is the moment it matters,
                  and both omissions are deliberate rules the CSV must keep. */}
              <p className="text-xs text-slate-400">
                Condition, description, weight and dimensions come from your standard
                defaults. Ad rate and Best Offer are never set by the CSV.
              </p>
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 dark:border-neutral-700 p-4">
          <button
            className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
            onClick={onClose}
          >
            {result ? 'Done' : 'Cancel'}
          </button>
          <button
            className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            onClick={() => result && download(result)}
            disabled={!result || result.drafts.length === 0}
          >
            <Download size={14} />
            Download {result ? result.drafts.length : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
