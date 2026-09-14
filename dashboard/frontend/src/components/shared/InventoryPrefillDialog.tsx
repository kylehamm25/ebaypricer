import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Download, Loader2 } from 'lucide-react'
import { apiPost } from '../../lib/api'
import type { PrefillResponse } from '../../types'

const STEP = 'text-sm text-slate-600 dark:text-neutral-300'
const STEP_NUM =
  'shrink-0 w-5 h-5 rounded-full bg-slate-100 dark:bg-neutral-700 text-slate-600 ' +
  'dark:text-neutral-300 text-xs font-medium grid place-items-center'

/** The filled workbook, decoded from base64 straight to a file. */
function download(filename: string, workbook: string) {
  const bytes = Uint8Array.from(atob(workbook), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(
    new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }),
  )
  const a = document.createElement('a')
  a.href = url
  // Distinguished from the blank template it was made from, so the two don't sit in
  // the Downloads folder under one name.
  a.download = filename.replace(/\.xlsx$/i, '') + '-filled.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

/** Step 1 of eBay's prefill round trip: fill their template with the selected cards.
 *
 *  Builds on open and asks nothing. The template is eBay's own workbook — their
 *  instructions say not to change its formatting, so the app can only fill in theirs —
 *  and it is kept on the Settings page, since it is one unchanging file every export
 *  needs. Rows are appended below whatever is already in it, so a template part-filled
 *  by hand keeps what was typed.
 *
 *  Steps 2 and 3 are Seller Hub's: you upload the filled file there, eBay returns its
 *  suggested categories, titles and aspects, and you finish that file and upload it
 *  again. This app does not touch the returned file. */
export function InventoryPrefillDialog({ ids, onClose }: {
  ids: number[]
  onClose: () => void
}) {
  const build = useMutation({
    mutationFn: () => apiPost('/inventory/prefill-template', { ids }) as Promise<PrefillResponse>,
  })

  // Once per open. `ids` is a fresh array each render, so it deliberately isn't a
  // dependency — the dialog is unmounted and remounted to export a different
  // selection.
  const run = build.mutate
  useEffect(() => { run() }, [run])

  const result = build.data

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="p-5 pb-3">
          <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100">
            Prefill template for {ids.length} {ids.length === 1 ? 'item' : 'items'}
          </h2>
        </div>

        <div className="px-5 pb-5 overflow-y-auto space-y-4">
          {build.isPending && (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-neutral-400">
              <Loader2 size={16} className="animate-spin" /> Filling it in...
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
              <p className="text-sm text-slate-600 dark:text-neutral-300">
                Wrote {result.drafts.length}{' '}
                {result.drafts.length === 1 ? 'row' : 'rows'} to{' '}
                <span className="font-medium text-slate-800 dark:text-neutral-100">{result.sheet}</span>,
                starting at row {result.first_row}.
              </p>

              {/* The rest of the round trip, because both remaining steps happen in
                  Seller Hub and nothing on this screen would otherwise say so. */}
              <ol className="space-y-2">
                <li className="flex gap-2.5">
                  <span className={STEP_NUM}>2</span>
                  <span className={STEP}>
                    Upload the downloaded file to Seller Hub. eBay returns a file of
                    suggested categories, titles and aspects.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className={STEP_NUM}>3</span>
                  <span className={STEP}>
                    Review that file, complete it and upload it again to create the
                    listings.
                  </span>
                </li>
              </ol>

              {result.missing_columns.length > 0 && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  Your stored template has no{' '}
                  {result.missing_columns.map((c) => c.replace(/_/g, ' ')).join(', ')} column,
                  so that data was left out.
                </p>
              )}

              {result.drafts.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-slate-500 dark:text-neutral-400">
                        <th className="py-1 pr-3 font-medium">Title</th>
                        <th className="py-1 pr-3 font-medium w-20">Lot</th>
                        <th className="py-1 font-medium w-16 text-right">Photos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.drafts.map((d) => (
                        <tr key={d.id} className="border-t border-slate-100 dark:border-neutral-700 align-top">
                          <td className="py-1.5 pr-3">
                            <div className="text-slate-800 dark:text-neutral-100">{d.title}</div>
                            <div className="text-xs text-slate-400 break-all">{d.aspects}</div>
                            {d.warnings.map((w) => (
                              <div key={w} className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                                {w}
                              </div>
                            ))}
                          </td>
                          <td className="py-1.5 pr-3 text-slate-600 dark:text-neutral-300">
                            {d.custom_label || <span className="text-slate-400">—</span>}
                          </td>
                          <td className="py-1.5 tabular-nums text-right text-slate-600 dark:text-neutral-300">
                            {d.photo_urls ? d.photo_urls.split('|').length : 0}
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
                  Nothing in this selection can be prefilled.
                </p>
              )}
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
            onClick={() => result && download(result.filename, result.workbook)}
            disabled={!result || result.drafts.length === 0}
          >
            <Download size={14} />
            Download filled template
          </button>
        </div>
      </div>
    </div>
  )
}
