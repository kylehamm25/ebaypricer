import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Search, Trash2, Loader2, AlertTriangle, Boxes, Pencil, ExternalLink, Minus, Plus } from 'lucide-react'
import { api, apiPut } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { formatCurrency } from '../lib/utils'
import { KpiCard } from '../components/shared/KpiCard'
import { CardArt } from '../components/shared/ViewToggle'
import type { CardHit, CardValue, LotsResponse } from '../types'

// Matches CONDITION_MULTIPLIER in services/suggested_price.py. Kept as labels only -
// the multiplier itself is applied server-side so this page can never disagree with
// the rest of the app about what a grade is worth.
const CONDITIONS = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged']

interface Row {
  id: number
  card: CardHit
  condition: string
  qty: number
  value?: CardValue
  loading: boolean
  error?: string
  /** Priced by hand instead of from eBay comps - no lookup, no condition multiplier. */
  manual?: boolean
  /** The typed price, kept as a string so a half-entered "12." doesn't reset the field. */
  price?: string
}

function CardSprite({ card }: { card: CardHit }) {
  // Catalog cards have real art. A custom search has no catalog card at all, so
  // there is nothing to show but a card back - which is honest, where the species
  // sprite it used to fall back to was a guess dressed up as a picture.
  return <CardArt artUrl={card.image_url} className="w-16 rounded" />
}

function nextSku(lots: { sku: string }[]): string {
  const nums = lots
    .map((l) => /^L(\d+)$/i.exec(l.sku)?.[1])
    .filter((n): n is string => Boolean(n))
    .map(Number)
  const next = nums.length ? Math.max(...nums) + 1 : 1
  return `L${String(next).padStart(4, '0')}`
}

// The one highlight style for the search dropdown, shared by hover and the arrow keys.
const HIGHLIGHT = 'bg-slate-50 dark:bg-neutral-700/50'

const FIELD =
  'w-full bg-slate-50 dark:bg-neutral-700/50 rounded-lg px-2 py-1 text-sm outline-none ' +
  'text-slate-900 dark:text-neutral-100'

// Mirrors MAX_QUERY_WORDS in src/ebaypricer/browse_api.py, which truncates every query
// before it reaches eBay. It matters most here: "Terapagos 161 Surging Sparks Horizons
// Stamped Promo" loses "Stamped Promo" - precisely the words that make the search worth
// doing - so the UI shows what will actually be searched rather than failing quietly.
const MAX_QUERY_WORDS = 5

// A free-text search, for cards the catalog cannot express. Stamped promos are the
// motivating case: a Regional Championships stamp is not a separate catalog entry, so
// picking the base card prices it against ordinary copies (measured: $1.37 against a
// $22.39 stamped pool). Typing the stamp gives it its own comp pool instead.
function customHit(query: string): CardHit {
  const q = query.trim()
  return { card_query: q, name: q, set_name: '', number: '', rarity: '', set_series: '', image_url: null }
}

// A hand-priced entry. Same shape as a custom search so the sprite path works, but it
// never reaches eBay - the seller states the value outright.
function manualHit(name: string): CardHit {
  return customHit(name)
}

// One row of the search dropdown: a catalog hit, or one of the two fallbacks offered
// when the catalog has nothing (or the wrong thing) for what was typed.
type Option = { kind: 'card'; card: CardHit } | { kind: 'custom' } | { kind: 'manual' }

// Catalog hits always carry a number and set; a free-text entry carries neither.
function isCustom(card: CardHit): boolean {
  return !card.number && !card.set_name
}

// In-progress valuations survive a refresh. Stored per user rather than per browser so
// two accounts on one machine don't inherit each other's draft.
//
// The fetched CardValue is stored ALONGSIDE the cards, not re-fetched on load: an
// uncached card costs a live eBay call, so restoring a 25-card draft on a new day would
// silently fire 25 of them just by opening the page. Each value carries its
// snapshot_date, so stale numbers are visible rather than pretended fresh.
const DRAFT_VERSION = 1
const draftKey = (userId: string | undefined) => `ebayprice.valuation.v${DRAFT_VERSION}.${userId ?? 'anon'}`

interface Draft {
  rows: Row[]
  offer: string
  /** The half-filled Create-lot form. Part of the same working state as the card list -
   *  losing a typed SKU and source to a refresh is the same annoyance as losing the
   *  cards. `saved`/`error` are deliberately not kept: they are transient feedback about
   *  one submission, and replaying "Lot L0042 saved" after a reload would be a lie. */
  lot?: { open: boolean; sku: string; title: string; source: string; date: string }
}

function loadDraft(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const d = JSON.parse(raw) as Draft
    // Never trust what came out of storage: a hand-edited or half-written entry should
    // start an empty page, not crash it.
    if (!d || !Array.isArray(d.rows)) return null
    const rows = d.rows.filter((r) => r && r.card && typeof r.card.card_query === 'string')
    return {
      // manual/price/lot are absent from drafts written before they existed, so default
      // rather than discarding the whole draft over a field that simply wasn't written.
      rows: rows.map((r) => ({ ...r, loading: false, manual: r.manual ?? false, price: r.price ?? '' })),
      offer: typeof d.offer === 'string' ? d.offer : '',
      lot: d.lot && typeof d.lot === 'object' ? d.lot : undefined,
    }
  } catch {
    return null
  }
}

let nextId = 1

export function ValuationPage() {
  const { user } = useAuth()
  const storageKey = draftKey(user?.id)
  // Which key the current rows were restored for. A boolean "have we restored yet" is
  // not enough: when the user changes, both effects re-run in the same commit and the
  // save effect would still be holding the previous user's rows, writing them under the
  // new user's key.
  const restoredFor = useRef<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CardHit[]>([])
  const [open, setOpen] = useState(false)
  // Which dropdown entry the arrow keys are on. Indexes `options` below, not `hits`:
  // the two trailing actions ("search eBay", "my own price") are selectable rows too.
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLUListElement>(null)
  const [searching, setSearching] = useState(false)
  const [rows, setRows] = useState<Row[]>([])
  const [offer, setOffer] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)
  const [lotOpen, setLotOpen] = useState(false)
  const [lotSku, setLotSku] = useState('')
  const [lotTitle, setLotTitle] = useState('')
  const [lotSource, setLotSource] = useState('')
  const [lotDate, setLotDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [lotSaving, setLotSaving] = useState(false)
  const [lotError, setLotError] = useState<string | null>(null)
  const [lotSaved, setLotSaved] = useState<string | null>(null)

  useEffect(() => {
    const d = loadDraft(storageKey)
    setRows(d?.rows ?? [])
    setOffer(d?.offer ?? '')
    setLotOpen(d?.lot?.open ?? false)
    setLotSku(d?.lot?.sku ?? '')
    setLotTitle(d?.lot?.title ?? '')
    setLotSource(d?.lot?.source ?? '')
    setLotDate(d?.lot?.date ?? new Date().toISOString().slice(0, 10))
    setLotSaved(null)
    setLotError(null)
    // Row ids come from a module counter that restarts at 1 on every page load. Without
    // this, a restored row and a freshly added one share an id and React reconciles the
    // wrong row.
    nextId = Math.max(0, ...(d?.rows ?? []).map((r) => r.id)) + 1
    restoredFor.current = storageKey
  }, [storageKey])

  useEffect(() => {
    if (restoredFor.current !== storageKey) return
    const lot = { open: lotOpen, sku: lotSku, title: lotTitle, source: lotSource, date: lotDate }
    const empty = rows.length === 0 && !offer && !lotOpen && !lotSku
    try {
      if (empty) localStorage.removeItem(storageKey)
      else localStorage.setItem(storageKey, JSON.stringify({ rows, offer, lot }))
    } catch {
      // Quota exceeded or storage blocked (private mode). The page works fine without
      // persistence, so this must not surface as an error.
    }
  }, [rows, offer, storageKey, lotOpen, lotSku, lotTitle, lotSource, lotDate])

  // Debounced so typing doesn't fire a request per keystroke. Search itself is a local
  // scan on the server (no eBay call), so this is purely about request volume.
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) { setHits([]); return }
    setSearching(true)
    const t = setTimeout(() => {
      api<CardHit[]>(`/valuation/cards/search?q=${encodeURIComponent(q)}&limit=15`)
        .then((r) => { setHits(r); setOpen(true) })
        .catch(() => setHits([]))
        .finally(() => setSearching(false))
    }, 200)
    return () => { clearTimeout(t); setSearching(false) }
  }, [query])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  async function fetchValue(id: number, card: CardHit, condition: string) {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, loading: true, error: undefined } : r)))
    try {
      const v = await api<CardValue>(
        `/valuation/card?card_query=${encodeURIComponent(card.card_query)}&condition=${encodeURIComponent(condition)}`,
      )
      setRows((rs) => rs.map((r) => (r.id === id ? { ...r, value: v, loading: false } : r)))
    } catch {
      setRows((rs) => rs.map((r) => (r.id === id ? { ...r, loading: false, error: 'Lookup failed' } : r)))
    }
  }

  async function fetchManual(id: number, name: string, price: string) {
    const p = parseFloat(price)
    if (isNaN(p) || p < 0) return
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, loading: true, error: undefined } : r)))
    try {
      const v = await api<CardValue>(
        `/valuation/manual?name=${encodeURIComponent(name)}&price=${encodeURIComponent(String(p))}`,
      )
      setRows((rs) => rs.map((r) => (r.id === id ? { ...r, value: v, loading: false } : r)))
    } catch {
      setRows((rs) => rs.map((r) => (r.id === id ? { ...r, loading: false, error: 'Could not price' } : r)))
    }
  }

  // Recompute any hand-priced row whose typed price no longer matches its computed
  // value, debounced so typing "12.50" is one request rather than five. Settles because
  // fetchManual writes adjusted_value back to the same number the test compares against.
  useEffect(() => {
    const stale = rows.filter(
      (r) => r.manual && r.price && !r.loading && (r.value?.adjusted_value ?? null) !== parseFloat(r.price),
    )
    if (!stale.length) return
    const t = setTimeout(() => {
      stale.forEach((r) => void fetchManual(r.id, r.card.name, r.price ?? ''))
    }, 400)
    return () => clearTimeout(t)
  }, [rows])

  function addManual(name: string) {
    const id = nextId++
    // Prepended, not appended: the card you just added is the one you want to see, and
    // on a long pile the bottom of the table is off screen.
    setRows((rs) => [{ id, card: manualHit(name), condition: 'Near Mint', qty: 1, loading: false, manual: true, price: '' }, ...rs])
    setQuery(''); setHits([]); setOpen(false)
  }

  function addCard(card: CardHit) {
    const id = nextId++
    const condition = 'Near Mint'
    setRows((rs) => [{ id, card, condition, qty: 1, loading: true }, ...rs])
    setQuery(''); setHits([]); setOpen(false)
    void fetchValue(id, card, condition)
  }

  function setQty(id: number, qty: number) {
    setRows((rs) => rs.map((x) => (x.id === id ? { ...x, qty: Math.max(1, qty) } : x)))
  }

  function setCondition(id: number, condition: string) {
    const row = rows.find((r) => r.id === id)
    if (!row) return
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, condition } : r)))
    void fetchValue(id, row.card, condition)
  }

  async function openLotForm() {
    setLotOpen(true); setLotError(null); setLotSaved(null)
    setLotTitle(`${totals.cards} cards`)
    try {
      const res = await api<LotsResponse>('/lots')
      if (!res.cost_tracking_enabled) {
        setLotError('Lot cost tracking needs db/migrations/0008_lots.sql to be run first.')
        return
      }
      setLotSku(nextSku(res.lots))
    } catch {
      setLotError('Could not read existing lots to suggest a SKU - enter one manually.')
    }
  }

  async function saveLot() {
    const sku = lotSku.trim()
    if (!sku) {
      setLotError('A SKU is required - it is what ties listings back to this lot.')
      return
    }
    setLotSaving(true); setLotError(null)
    try {
      await apiPut(`/lots/${encodeURIComponent(sku)}`, {
        title: lotTitle.trim() || null,
        // The price you'd pay IS the lot's cost basis - that is the number the Lots
        // page measures every later sale against.
        cost: hasOffer ? offerNum : null,
        purchased_at: lotDate || null,
        source: lotSource.trim() || null,
        notes:
          `Valued before purchase: ${totals.cards} cards, ${formatCurrency(totals.asking)} market, ` +
          `${formatCurrency(totals.net)} est. net after fees.`,
      })
      setLotSaved(sku)
      setLotOpen(false)
    } catch (e) {
      setLotError(e instanceof Error ? e.message : 'Could not save the lot.')
    } finally {
      setLotSaving(false)
    }
  }

  const totals = useMemo(() => {
    let asking = 0, net = 0, cards = 0, priced = 0, missing = 0, unfiltered = 0
    for (const r of rows) {
      cards += r.qty
      // 'manual' counts toward the totals exactly like 'ok' - a hand-typed price is
      // still a price. It must NOT count toward `unfiltered` though: that warning is
      // about comp pools predating comp filtering, and a manual row has no comps at all.
      const usable = r.value?.status === 'ok' || r.value?.status === 'manual'
      if (usable && r.value && r.value.adjusted_value != null) {
        asking += r.value.adjusted_value * r.qty
        net += (r.value.estimated_net ?? 0) * r.qty
        priced += r.qty
        if (!r.manual && !r.value.pool_quality) unfiltered += 1
      } else if (!r.loading) missing += r.qty
    }
    return { asking, net, cards, priced, missing, unfiltered }
  }, [rows])

  // The dropdown flattened into one selectable list, so the keyboard doesn't have to
  // know that the last two rows are actions rather than catalog hits.
  const options = useMemo<Option[]>(() => {
    const o: Option[] = hits.map((card) => ({ kind: 'card', card }))
    if (query.trim().length >= 2) o.push({ kind: 'custom' }, { kind: 'manual' })
    return o
  }, [hits, query])

  // A new result set means the old highlight points at a different card - start over at
  // the top rather than leaving it on whatever now happens to occupy that index.
  useEffect(() => { setActive(0) }, [options])

  // The list scrolls (max-h-80), so arrowing past the fold has to bring the row along.
  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  function choose(i: number) {
    const o = options[i]
    if (!o) return
    if (o.kind === 'card') addCard(o.card)
    else if (o.kind === 'custom') addCard(customHit(query))
    else addManual(query.trim())
  }

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!options.length) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      // Arrowing on a closed dropdown reopens it rather than moving an invisible
      // highlight, which is what a search field that still holds a query should do.
      if (!open) { setOpen(true); return }
      const d = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i + d + options.length) % options.length)
    } else if (e.key === 'Enter') {
      if (!open) return
      e.preventDefault()
      choose(active)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const offerNum = parseFloat(offer)
  const hasOffer = !isNaN(offerNum) && offerNum > 0
  const profit = hasOffer ? totals.net - offerNum : 0
  const roi = hasOffer && offerNum > 0 ? (profit / offerNum) * 100 : 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Card Valuation</h1>
      </div>

      <div ref={boxRef} className="relative max-w-2xl">
        <div className="flex items-center gap-2 bg-white dark:bg-neutral-800 rounded-xl px-3 py-2">
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => hits.length && setOpen(true)}
            onKeyDown={onSearchKeyDown}
            role="combobox"
            aria-expanded={open}
            aria-controls="valuation-search-results"
            aria-activedescendant={open ? `valuation-option-${active}` : undefined}
            placeholder="Search a card"
            className="w-full bg-transparent outline-none text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400"
          />
          {searching && <Loader2 className="w-4 h-4 animate-spin text-slate-400 shrink-0" />}
        </div>

        {open && (hits.length > 0 || query.trim().length >= 2) && (
          <ul
            ref={listRef}
            id="valuation-search-results"
            role="listbox"
            className="absolute z-20 mt-1 w-full max-h-80 overflow-y-auto bg-white dark:bg-neutral-800 rounded-xl shadow-lg ring-1 ring-black/5 dark:ring-white/10"
          >
            {hits.map((h, i) => (
              <li key={h.card_query + h.number}>
                <button
                  id={`valuation-option-${i}`}
                  data-idx={i}
                  role="option"
                  aria-selected={active === i}
                  // Hovering moves the highlight instead of drawing a second one, so the
                  // mouse and the arrow keys can never disagree about what Enter picks.
                  onMouseEnter={() => setActive(i)}
                  onClick={() => addCard(h)}
                  className={`w-full text-left px-3 py-2 ${active === i ? HIGHLIGHT : ''}`}
                >
                  <span className="text-sm text-slate-900 dark:text-neutral-100">{h.name}</span>
                  <span className="text-xs text-slate-500 dark:text-neutral-400 ml-2">
                    #{h.number} · {h.set_name}
                  </span>
                  {/* Rarity as a badge rather than more run-on text: it is what separates
                      two printings that share a name, number and set, and it drives price
                      more than anything else visible here. */}
                  {h.rarity && (
                    <span className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 dark:bg-neutral-700 text-slate-600 dark:text-neutral-300 align-middle">
                      {h.rarity}
                    </span>
                  )}
                </button>
              </li>
            ))}
            {query.trim().length >= 2 && (
              <li className={hits.length ? 'border-t border-slate-100 dark:border-neutral-700' : undefined}>
                <button
                  id={`valuation-option-${hits.length}`}
                  data-idx={hits.length}
                  role="option"
                  aria-selected={active === hits.length}
                  onMouseEnter={() => setActive(hits.length)}
                  onClick={() => addCard(customHit(query))}
                  className={`w-full text-left px-3 py-2 ${active === hits.length ? HIGHLIGHT : ''}`}
                >
                  <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                    <Search className="w-3.5 h-3.5" />
                    Search eBay for <span className="font-medium text-slate-900 dark:text-neutral-100">"{query.trim()}"</span>
                  </span>
                  {query.trim().split(/\s+/).length > MAX_QUERY_WORDS ? (
                    <span className="block text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                      eBay only uses the first {MAX_QUERY_WORDS} words:{' '}
                      <strong>{query.trim().split(/\s+/).slice(0, MAX_QUERY_WORDS).join(' ')}</strong>
                      {' '}— put the words that matter first
                    </span>
                  ) : (
                    <span className="block text-xs text-slate-400 mt-0.5">
                    </span>
                  )}
                </button>
              </li>
            )}
            {query.trim().length >= 2 && (
              <li className="border-t border-slate-100 dark:border-neutral-700">
                <button
                  id={`valuation-option-${hits.length + 1}`}
                  data-idx={hits.length + 1}
                  role="option"
                  aria-selected={active === hits.length + 1}
                  onMouseEnter={() => setActive(hits.length + 1)}
                  onClick={() => addManual(query.trim())}
                  className={`w-full text-left px-3 py-2 ${active === hits.length + 1 ? HIGHLIGHT : ''}`}
                >
                  <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                    <Pencil className="w-3.5 h-3.5" />
                    Add <span className="font-medium text-slate-900 dark:text-neutral-100">"{query.trim()}"</span> with my own price
                  </span>
                  <span className="block text-xs text-slate-400 mt-0.5">
                  </span>
                </button>
              </li>
            )}
          </ul>
        )}
      </div>

      {rows.length > 0 && (
        <>
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
            <KpiCard title="Cards" value={String(totals.cards)} />
            <KpiCard title="Market Value" value={formatCurrency(totals.asking)} />
            <KpiCard title="Est. Net After Fees" value={formatCurrency(totals.net)} />
            <KpiCard
              title="Profit"
              // ROI rides along in the value so the number survives without a subtitle line.
              value={hasOffer ? `${formatCurrency(profit)} (${roi >= 0 ? '+' : ''}${roi.toFixed(0)}%)` : '—'}
              tone={hasOffer ? (profit >= 0 ? 'positive' : 'negative') : 'default'}
            />
          </div>

          <div className="flex items-center gap-2 text-sm">
            <label className="text-slate-500 dark:text-neutral-400">Price:</label>
            <input
              type="number" min="0" step="0.01" value={offer}
              onChange={(e) => setOffer(e.target.value)}
              placeholder="0.00"
              // Spinners hidden: stepping a price 1c at a time is useless, and they eat
              // width in a narrow field. type="number" is kept for the numeric keypad on
              // mobile and the min/step validation. [appearance:textfield] covers Firefox;
              // the pseudo-element rules cover Chrome/Safari, which ignore it.
              className="w-32 bg-white dark:bg-neutral-800 rounded-lg px-2 py-1 outline-none text-slate-900 dark:text-neutral-100 [appearance:textfield] [&::-webkit-outer-spin-button]:[-webkit-appearance:none] [&::-webkit-inner-spin-button]:[-webkit-appearance:none] [&::-webkit-outer-spin-button]:m-0 [&::-webkit-inner-spin-button]:m-0"
            />
            <button
              onClick={openLotForm}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm bg-slate-900 text-white hover:bg-slate-700 dark:bg-neutral-700 dark:hover:bg-neutral-600"
            >
              <Boxes className="w-4 h-4" /> Create lot
            </button>
            <button
              onClick={() => {
                setRows([]); setOffer(''); setLotSaved(null); setLotError(null)
                setLotOpen(false); setLotSku(''); setLotTitle(''); setLotSource('')
              }}
              className="text-sm text-slate-500 dark:text-neutral-400 hover:underline"
            >
              Clear
            </button>
          </div>

          {lotSaved && (
            <div className="flex flex-wrap items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 rounded-lg px-3 py-2">
              <span>Lot <strong>{lotSaved}</strong> saved.</span>
              <Link to="/lots" className="underline">View on the Lots page</Link>
            </div>
          )}

          {lotOpen && (
            <div className="bg-white dark:bg-neutral-800 rounded-xl p-4 space-y-3 max-w-2xl">
              <div className="grid gap-3 sm:grid-cols-2">
                <label>
                  <span className="block text-xs text-slate-500 dark:text-neutral-400 mb-1">SKU</span>
                  <input value={lotSku} onChange={(e) => setLotSku(e.target.value)} className={FIELD} />
                </label>
                <label>
                  <span className="block text-xs text-slate-500 dark:text-neutral-400 mb-1">Title</span>
                  <input value={lotTitle} onChange={(e) => setLotTitle(e.target.value)} className={FIELD} />
                </label>
                <label>
                  <span className="block text-xs text-slate-500 dark:text-neutral-400 mb-1">Purchased</span>
                  <input type="date" value={lotDate} onChange={(e) => setLotDate(e.target.value)} className={FIELD} />
                </label>
                <label>
                  <span className="block text-xs text-slate-500 dark:text-neutral-400 mb-1">Source</span>
                  <input value={lotSource} onChange={(e) => setLotSource(e.target.value)} placeholder="seller, show, shop" className={FIELD} />
                </label>
              </div>

              {/* Cost is not a second input: it is the Price field above. Two boxes for one
                  number is how they drift apart. */}
              <p className="text-xs text-slate-500 dark:text-neutral-400">
                Cost: <strong>{hasOffer ? formatCurrency(offerNum) : 'not set'}</strong> — taken from the Price
                field above.{!hasOffer && ' Enter one first, or the lot saves with no cost basis and shows no profit.'}
              </p>

              {/* The thing that will otherwise look broken: lots are keyed by the SKU on
                  the LISTINGS, so a brand new lot has nothing attached to it yet. */}
              <p className="text-xs text-slate-500 dark:text-neutral-400">
                The lot will show 0 cards until your eBay listings carry SKU <strong>{lotSku || 'this SKU'}</strong>.
                That SKU is what ties cards back to the lot.
              </p>

              {lotError && <p className="text-xs text-amber-600 dark:text-amber-400">{lotError}</p>}

              <div className="flex items-center gap-2">
                <button
                  onClick={saveLot}
                  disabled={lotSaving}
                  className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-neutral-700 dark:hover:bg-neutral-600"
                >
                  {lotSaving && <Loader2 className="w-4 h-4 animate-spin" />} Save lot
                </button>
                <button onClick={() => setLotOpen(false)} className="text-sm text-slate-500 dark:text-neutral-400 hover:underline">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {totals.unfiltered > 0 && (
            <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 rounded-lg px-3 py-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                {totals.unfiltered} card{totals.unfiltered === 1 ? "'s" : "s'"} comps could not be refreshed, so
                {totals.unfiltered === 1 ? ' its' : ' their'} value falls back to an unfiltered snapshot that may
                include graded slabs, lots or wrong prints. Remove and re-add to try again.
              </span>
            </div>
          )}

          <div className="bg-white dark:bg-neutral-800 rounded-xl overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-neutral-400">
                  <th className="text-left font-medium px-4 py-3">Card</th>
                  <th className="text-left font-medium px-4 py-3">Condition</th>
                  <th className="text-right font-medium px-4 py-3">Qty</th>
                  <th className="text-right font-medium px-4 py-3">Market</th>
                  <th className="text-right font-medium px-4 py-3">Adjusted</th>
                  <th className="text-right font-medium px-4 py-3">Est. Net</th>
                  <th className="text-left font-medium px-4 py-3">Comps</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const v = r.value
                  const pq = v?.pool_quality
                  return (
                    <tr key={r.id} className="border-t border-slate-100 dark:border-neutral-700/60">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <CardSprite card={r.card} />
                          <div>
                            <div className="text-slate-900 dark:text-neutral-100">{r.card.name}</div>
                            {r.manual ? (
                              <div className="text-xs text-slate-400 italic"></div>
                            ) : isCustom(r.card) ? (
                              <div className="text-xs text-slate-400 italic">Custom search</div>
                            ) : (
                              <div className="text-xs text-slate-500 dark:text-neutral-400">
                                #{r.card.number} · {r.card.set_name}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {r.manual ? (
                          <span className="text-xs text-slate-400">n/a</span>
                        ) : (
                        <>
                        <select
                          value={r.condition}
                          onChange={(e) => setCondition(r.id, e.target.value)}
                          // Same select styling as the other pages (ActiveListings, PriceLog,
                          // SoldOrders). bg-transparent was the bug: the native option popup
                          // takes its colour from the select's own background, so a transparent
                          // one fell back to the browser default (white) in dark mode. No
                          // color-scheme needed here - theme.tsx already sets it on <html> and
                          // the property inherits.
                          className="border border-slate-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-slate-700 dark:text-neutral-100 rounded-lg px-2 py-1 text-sm outline-none"
                        >
                          {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                        {v && v.condition_mult !== 1 && (
                          <span className="text-xs text-slate-400 ml-1">×{v.condition_mult}</span>
                        )}
                        </>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {/* Explicit buttons instead of the native number spinner. Those
                            arrows are a few pixels tall, are hidden until hover in some
                            browsers, and - worst here - a focused number input changes
                            value on scroll, so scrolling a long pile silently rewrites
                            quantities. type="text" + inputMode="numeric" keeps the
                            numeric keypad on mobile without any of that. */}
                        <div className="inline-flex items-center gap-0.5">
                          <button
                            onClick={() => setQty(r.id, r.qty - 1)}
                            disabled={r.qty <= 1}
                            aria-label="Decrease quantity"
                            className="w-6 h-6 rounded flex items-center justify-center text-slate-500 dark:text-neutral-400 hover:bg-slate-100 dark:hover:bg-neutral-700 disabled:opacity-30 disabled:hover:bg-transparent"
                          >
                            <Minus className="w-3.5 h-3.5" />
                          </button>
                          <input
                            type="text"
                            inputMode="numeric"
                            value={r.qty}
                            // Select on focus so typing a two-digit quantity replaces the
                            // value outright; otherwise clearing the field fought the
                            // clamp, which snapped an empty box straight back to 1.
                            onFocus={(e) => e.currentTarget.select()}
                            onChange={(e) => {
                              const digits = e.target.value.replace(/\D/g, '')
                              if (digits) setQty(r.id, parseInt(digits, 10))
                            }}
                            aria-label="Quantity"
                            className="w-8 bg-transparent text-center outline-none text-slate-900 dark:text-neutral-100"
                          />
                          <button
                            onClick={() => setQty(r.id, r.qty + 1)}
                            aria-label="Increase quantity"
                            className="w-6 h-6 rounded flex items-center justify-center text-slate-500 dark:text-neutral-400 hover:bg-slate-100 dark:hover:bg-neutral-700"
                          >
                            <Plus className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600 dark:text-neutral-300">
                        {r.manual ? (
                          <input
                            type="number" min="0" step="0.01" value={r.price ?? ''}
                            onChange={(e) => setRows((rs) => rs.map((x) => (x.id === r.id ? { ...x, price: e.target.value } : x)))}
                            placeholder="0.00"
                            className="w-20 bg-transparent text-right outline-none text-slate-900 dark:text-neutral-100 [appearance:textfield] [&::-webkit-outer-spin-button]:[-webkit-appearance:none] [&::-webkit-inner-spin-button]:[-webkit-appearance:none]"
                          />
                        ) : r.loading ? (
                          <Loader2 className="w-4 h-4 animate-spin inline text-slate-400" />
                        ) : v?.active_avg != null ? formatCurrency(v.active_avg) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-900 dark:text-neutral-100">
                        {v?.adjusted_value != null ? formatCurrency(v.adjusted_value * r.qty) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-emerald-600 dark:text-emerald-400">
                        {v?.estimated_net != null ? formatCurrency(v.estimated_net * r.qty) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 dark:text-neutral-400">
                        {r.error ? <span className="text-amber-600">{r.error}</span>
                          : r.manual ? <span className="text-slate-400">manual entry</span>
                          : v?.status === 'no_comps' ? 'no comps found'
                          : v ? (
                            <>
                              {v.comps ?? 0} kept
                              {pq && pq.dropped > 0 && <span className="text-slate-400"> · {pq.dropped} dropped</span>}
                              {!pq && <span className="text-amber-600 dark:text-amber-400"> · unfiltered</span>}
                              {v.market_price != null && (
                                <div className="text-slate-400">TCG {formatCurrency(v.market_price)}</div>
                              )}
                            </>
                          ) : (
                            // A row saved to the draft mid-lookup comes back with no value.
                            // Offered as a button rather than re-fetched on load: restoring
                            // a big draft would otherwise fire a live eBay call per card.
                            <button
                              onClick={() => void fetchValue(r.id, r.card, r.condition)}
                              className="text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              Value this card
                            </button>
                          )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex items-center gap-2">
                          {/* Opens the exact search the comps came from - same query,
                              negative keywords, category and Buy It Now filter. The
                              fastest way to answer "why is this number wrong?". */}
                          {v?.search_url && (
                            <a
                              href={v.search_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="View this search on eBay"
                              aria-label="View this search on eBay"
                              className="text-slate-400 hover:text-blue-500"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          )}
                          <button
                            onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                            className="text-slate-400 hover:text-red-500"
                            aria-label="Remove card"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
