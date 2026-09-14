import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Pencil, Search } from 'lucide-react'
import { api, apiPut } from '../../lib/api'
import type { CardHit } from '../../types'

const HIGHLIGHT = 'bg-slate-50 dark:bg-neutral-700/50'

// Mirrors MAX_QUERY_WORDS in src/ebaypricer/browse_api.py, which truncates every
// query before it reaches eBay.
const MAX_QUERY_WORDS = 5

type Option = { kind: 'card'; card: CardHit } | { kind: 'search' }

/** Correct which catalog card a listing prices against.
 *
 *  The match comes from fuzzy-matching the eBay title, which is wrong in the ways
 *  fuzzy matching is always wrong - the right card in the wrong set, the base print
 *  of a stamped promo. That is not cosmetic: it prices the listing against a
 *  different card, so it has to be correctable.
 *
 *  Saving locks the value so the next sync cannot re-derive it; "Use the automatic
 *  match" clears both the value and the lock and hands the row back to the matcher. */
export function CardMatchDialog({ itemId, current, locked, onClose }: {
  itemId: string
  current: string | null
  locked: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CardHit[]>([])
  const [searching, setSearching] = useState(false)
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) { setHits([]); return }
    setSearching(true)
    const t = setTimeout(() => {
      api<CardHit[]>(`/valuation/cards/search?q=${encodeURIComponent(q)}&limit=15`)
        .then(setHits)
        .catch(() => setHits([]))
        .finally(() => setSearching(false))
    }, 200)
    return () => { clearTimeout(t); setSearching(false) }
  }, [query])

  const typed = query.trim()
  const options: Option[] = [
    ...hits.map((card): Option => ({ kind: 'card', card })),
    ...(typed.length >= 2 ? [{ kind: 'search' } as Option] : []),
  ]

  useEffect(() => { setActive(0) }, [query, hits])
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const save = useMutation({
    mutationFn: (cardQuery: string | null) =>
      apiPut(`/active/item/${encodeURIComponent(itemId)}/card`, { card_query: cardQuery }),
    onSuccess: () => {
      // The suggested price and every comp figure on the page derive from the
      // match, so the whole listing is refetched rather than patched.
      queryClient.invalidateQueries({ queryKey: ['active-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['active-list'] })
      onClose()
    },
  })

  function choose(i: number) {
    const o = options[i]
    if (!o) return
    save.mutate(o.kind === 'card' ? o.card.card_query : typed)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 w-full max-w-md max-h-[85vh] flex flex-col">
        <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100">Which card is this?</h2>
        <p className="text-xs text-slate-500 dark:text-neutral-400 mt-1 mb-3">
          Currently{' '}
          <span className="text-slate-700 dark:text-neutral-200">{current || 'unmatched'}</span>
          {locked ? ' · set by hand' : ' · matched automatically'}
        </p>

        <div className="flex items-center gap-2 border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 rounded-lg px-3 py-2">
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <input
            value={query}
            autoFocus
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (!options.length) return
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                const d = e.key === 'ArrowDown' ? 1 : -1
                setActive((i) => (i + d + options.length) % options.length)
              } else if (e.key === 'Enter') {
                e.preventDefault()
                choose(active)
              }
            }}
            placeholder="Card name, set, or number"
            className="w-full bg-transparent outline-none text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400"
          />
          {(searching || save.isPending) && <Loader2 className="w-4 h-4 animate-spin text-slate-400 shrink-0" />}
        </div>

        <ul ref={listRef} className="mt-2 flex-1 min-h-0 overflow-y-auto">
          {hits.map((h, i) => (
            <li key={h.card_query + h.number}>
              <button
                type="button"
                data-idx={i}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(i)}
                className={`w-full text-left px-3 py-2 rounded-lg ${active === i ? HIGHLIGHT : ''}`}
              >
                <span className="text-sm text-slate-900 dark:text-neutral-100">{h.name}</span>
                <span className="text-xs text-slate-500 dark:text-neutral-400 ml-2">
                  #{h.number} · {h.set_name}
                </span>
                {h.rarity && (
                  <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 dark:bg-neutral-700 text-slate-600 dark:text-neutral-300 align-middle">
                    {h.rarity}
                  </span>
                )}
              </button>
            </li>
          ))}
          {typed.length >= 2 && (
            <li className={hits.length ? 'border-t border-slate-100 dark:border-neutral-700 mt-1 pt-1' : undefined}>
              <button
                type="button"
                data-idx={hits.length}
                onMouseEnter={() => setActive(hits.length)}
                onClick={() => choose(hits.length)}
                className={`w-full text-left px-3 py-2 rounded-lg ${active === hits.length ? HIGHLIGHT : ''}`}
              >
                <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                  <Pencil className="w-3.5 h-3.5" />
                  Price against an eBay search for{' '}
                  <span className="font-medium text-slate-900 dark:text-neutral-100">"{typed}"</span>
                </span>
                {typed.split(/\s+/).length > MAX_QUERY_WORDS && (
                  <span className="block text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                    eBay only uses the first {MAX_QUERY_WORDS} words:{' '}
                    <strong>{typed.split(/\s+/).slice(0, MAX_QUERY_WORDS).join(' ')}</strong>
                    {' '}— put the words that matter first
                  </span>
                )}
              </button>
            </li>
          )}
        </ul>

        {save.isError && (
          <p className="text-xs text-rose-600 dark:text-rose-400 mt-3">
            {(save.error as Error).message}
          </p>
        )}

        <div className="flex items-center justify-between gap-2 pt-4">
          {/* Only offered once there is a correction to undo - on an automatically
              matched listing it would do nothing. */}
          {locked ? (
            <button
              className="text-xs text-slate-500 dark:text-neutral-400 hover:text-slate-800 dark:hover:text-neutral-200"
              onClick={() => save.mutate(null)}
              disabled={save.isPending}
            >
              Use the automatic match
            </button>
          ) : <span />}
          <button
            className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
            onClick={onClose}
            disabled={save.isPending}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
