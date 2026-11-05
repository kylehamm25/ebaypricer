import { useEffect, useRef, useState } from 'react'
import { Loader2, Pencil, Search } from 'lucide-react'
import { api } from '../../lib/api'
import { CardFinishButtons } from './CardFinishButtons'
import { finishLabel } from '../../lib/cardFinish'
import type { CardFinish } from '../../lib/cardFinish'
import type { CardHit } from '../../types'

// Mirrors MAX_QUERY_WORDS in src/ebaypricer/browse_api.py, which truncates every
// query before it reaches eBay.
const MAX_QUERY_WORDS = 5

const HIGHLIGHT = 'bg-slate-50 dark:bg-neutral-700/50'

type Option =
  | { kind: 'card'; card: CardHit }
  | { kind: 'search' }
  | { kind: 'stated' }

export function CardSearch({
  onPick,
  onSearchTerm,
  onFreeText,
  autoFocus = true,
  placeholder = 'Card name, set, or number',
}: {
  onPick: (hit: CardHit, finish: CardFinish) => void
  onSearchTerm: (text: string) => void
  onFreeText: (text: string) => void
  autoFocus?: boolean
  placeholder?: string
}) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CardHit[]>([])
  const [searching, setSearching] = useState(false)
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) { setHits([]); return }
    let cancelled = false
    setSearching(true)
    const t = setTimeout(() => {
      api<CardHit[]>(`/valuation/cards/search?q=${encodeURIComponent(q)}&limit=15`)
        .then((next) => { if (!cancelled) setHits(next) })
        .catch(() => { if (!cancelled) setHits([]) })
        .finally(() => { if (!cancelled) setSearching(false) })
    }, 200)
    return () => { cancelled = true; clearTimeout(t); setSearching(false) }
  }, [query])

  const typed = query.trim()
  const options: Option[] = [
    ...hits.map((card): Option => ({ kind: 'card', card })),
    ...(typed.length >= 2 ? [{ kind: 'search' } as Option, { kind: 'stated' } as Option] : []),
  ]

  useEffect(() => { setActive(0) }, [query, hits])

  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  function reset() {
    setQuery('')
    setHits([])
  }

  function pickCard(hit: CardHit, finish: CardFinish = 'regular') {
    reset()
    onPick(hit, finish)
  }

  function pickSearchTerm(text: string) {
    reset()
    onSearchTerm(text)
  }

  function pickFreeText(text: string) {
    reset()
    onFreeText(text)
  }

  // finish defaults to 'regular' so Enter and the row's own click keep adding at
  // the same speed as before finishes existed - only the small buttons beside
  // each hit ask for anything else.
  function choose(i: number, finish: CardFinish = 'regular') {
    const option = options[i]
    if (!option) return
    if (option.kind === 'card') pickCard(option.card, finish)
    else if (option.kind === 'search') pickSearchTerm(typed)
    else pickFreeText(typed)
  }

  return (
    <div className="flex flex-col min-h-0">
      <div className="flex items-center gap-2 border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 rounded-lg px-3 py-2">
        <Search className="w-4 h-4 text-slate-400 shrink-0" />
        <input
          value={query}
          autoFocus={autoFocus}
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
          placeholder={placeholder}
          className="w-full bg-transparent outline-none text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400"
        />
        {searching && <Loader2 className="w-4 h-4 animate-spin text-slate-400 shrink-0" />}
      </div>

      <ul ref={listRef} className="mt-2 flex-1 min-h-0 overflow-y-auto -mx-1">
        {hits.map((hit, i) => (
          <li key={hit.card_query + hit.number} className={`flex items-center rounded-lg ${active === i ? HIGHLIGHT : ''}`}>
            <button
              type="button"
              data-idx={i}
              onMouseEnter={() => setActive(i)}
              onClick={() => pickCard(hit)}
              title={`Choose as ${finishLabel('regular')}`}
              className="min-w-0 flex-1 text-left px-3 py-2"
            >
              <span className="text-sm text-slate-900 dark:text-neutral-100">{hit.name}</span>
              <span className="text-xs text-slate-500 dark:text-neutral-400 ml-2">
                #{hit.number} - {hit.set_name}
              </span>
              {hit.rarity && (
                <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 dark:bg-neutral-700 text-slate-600 dark:text-neutral-300 align-middle">
                  {hit.rarity}
                </span>
              )}
            </button>
            <CardFinishButtons setName={hit.set_name} onPick={(finish) => pickCard(hit, finish)} />
          </li>
        ))}

        {typed.length >= 2 && (
          <li className={hits.length ? 'border-t border-slate-100 dark:border-neutral-700 mt-1 pt-1' : undefined}>
            <button
              type="button"
              data-idx={hits.length}
              onMouseEnter={() => setActive(hits.length)}
              onClick={() => pickSearchTerm(typed)}
              className={`w-full text-left px-3 py-2 rounded-lg ${active === hits.length ? HIGHLIGHT : ''}`}
            >
              <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                <Search className="w-3.5 h-3.5" />
                Price <span className="font-medium text-slate-900 dark:text-neutral-100">"{typed}"</span> from an eBay search
              </span>
              {typed.split(/\s+/).length > MAX_QUERY_WORDS && (
                <span className="block text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                  eBay only uses the first {MAX_QUERY_WORDS} words:{' '}
                  <strong>{typed.split(/\s+/).slice(0, MAX_QUERY_WORDS).join(' ')}</strong>
                  {' '}- put the words that matter first
                </span>
              )}
            </button>
          </li>
        )}
        {typed.length >= 2 && (
          <li className="border-t border-slate-100 dark:border-neutral-700 mt-1 pt-1">
            <button
              type="button"
              data-idx={hits.length + 1}
              onMouseEnter={() => setActive(hits.length + 1)}
              onClick={() => pickFreeText(typed)}
              className={`w-full text-left px-3 py-2 rounded-lg ${active === hits.length + 1 ? HIGHLIGHT : ''}`}
            >
              <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                <Pencil className="w-3.5 h-3.5" />
                Use <span className="font-medium text-slate-900 dark:text-neutral-100">"{typed}"</span> and price it myself
              </span>
            </button>
          </li>
        )}
      </ul>

      {typed.length < 2 && (
        <button
          type="button"
          onClick={() => pickFreeText('')}
          className="mt-2 text-left text-xs text-slate-500 dark:text-neutral-400 hover:text-slate-800 dark:hover:text-neutral-200"
        >
        </button>
      )}
    </div>
  )
}
