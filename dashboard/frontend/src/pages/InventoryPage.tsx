import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Pencil, Trash2, Search, AlertTriangle, Loader2, Minus, Plus, Sparkles, ExternalLink,
  Archive, ArchiveRestore, FileSpreadsheet, FileUp, Copy, ImagePlus,
} from 'lucide-react'
import { api, apiDelete, apiPost, apiPut } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { InventoryEditDialog } from '../components/shared/InventoryEditDialog'
import { InventoryBulkDialog } from '../components/shared/InventoryBulkDialog'
import { InventoryListingCsvDialog } from '../components/shared/InventoryListingCsvDialog'
import { InventoryPrefillDialog } from '../components/shared/InventoryPrefillDialog'
import { KpiSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { CardArt, GridShell, ViewToggle } from '../components/shared/ViewToggle'
import { CardFinishButtons } from '../components/shared/CardFinishButtons'
import { sortByName, uploadPhotos } from '../lib/photos'
import { applyFinish, finishLabel } from '../lib/cardFinish'
import type { CardFinish } from '../lib/cardFinish'
import { GRID_CLASS, useViewPreference } from '../lib/view-preference'
import { formatCurrency, formatInt } from '../lib/utils'
import type { CardHit, CardValue, InventoryItem, InventoryResponse, LotOption, LotsResponse } from '../types'

// Same vocabulary as CONDITION_MULTIPLIER in services/suggested_price.py. Labels
// only - the multiplier is applied server-side, so this list can never disagree
// with what a row is actually valued at.
const CONDITIONS = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged']

const SELECT =
  'bg-white dark:bg-neutral-800 text-slate-700 dark:text-neutral-200 rounded-lg px-3 py-2 text-sm outline-none'

const SEED_FIELD =
  'bg-white dark:bg-neutral-800 text-slate-700 dark:text-neutral-200 rounded-lg px-3 py-2 text-sm outline-none ' +
  'placeholder:text-slate-400 w-36'

// A set seed field is a standing instruction, not just a filled-in box.
const SEED_ACTIVE = 'ring-1 ring-blue-500/60 text-slate-900 dark:text-neutral-100'

const HIGHLIGHT = 'bg-slate-50 dark:bg-neutral-700/50'

// Mirrors MAX_BATCH in routers/valuation.py, which rejects anything larger. Each
// uncached card in a batch is a live Browse call made inside a request handler, so
// this ceiling is the whole reason pricing here is a deliberate action and not
// something the page does to itself on load.
const MAX_PRICE_BATCH = 25

// Mirrors MAX_QUERY_WORDS in src/ebaypricer/browse_api.py, which truncates every
// query before it reaches eBay. Shown rather than left to fail quietly: "Terapagos
// 161 Surging Sparks Horizons Stamped Promo" loses "Stamped Promo", which is
// precisely what made the search worth running.
const MAX_QUERY_WORDS = 5

// Cataloguing a box is not one sitting: you add a handful, go look something up,
// come back. The seed condition and lot therefore outlive the page, stored per user
// rather than per browser so two accounts on one machine don't inherit each
// other's - the same reasoning as the Valuation page's saved draft.
const SEED_VERSION = 1
const seedKey = (userId: string | undefined) =>
  `ebayprice.inventory.seed.v${SEED_VERSION}.${userId ?? 'anon'}`

// The same keys routers/inventory.py accepts (most in _SORT_COLS; 'type' is the one
// exception, sorted in Python there since it has no column of its own). The grid has
// no column headers to click, so it needs these spelled out.
const SORTS: { key: string; label: string }[] = [
  { key: 'type', label: 'Card Type' },
  { key: 'added', label: 'Recently added' },
  { key: 'name', label: 'Name' },
  { key: 'number', label: 'Card #' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'condition', label: 'Condition' },
  { key: 'location', label: 'Location' },
  { key: 'sku', label: 'Lot' },
  { key: 'cost', label: 'Cost' },
]

/** What to show as the tile/row's picture: a real photo of the actual card in hand
 *  beats catalog art of the printing in general, whenever there is one. `photo_urls`
 *  is already ordered with the main image first - the same field the prefill flow
 *  and every export read to identify the item - so this is just "first or none". */
function coverArt(item: InventoryItem): string | null {
  const first = item.photo_urls?.split('|')[0]?.trim()
  return first || item.card_image_url
}

/** The whole row as the API wants it back, with the edited fields overridden.
 *  PUT replaces the row, so an inline edit has to resend everything it isn't
 *  changing - sending only the changed field would blank the rest. */
function itemBody(item: InventoryItem, patch: Partial<Record<string, unknown>>) {
  return {
    name: item.name,
    card_query: item.card_query,
    set_name: item.set_name,
    number: item.number,
    condition: item.condition,
    quantity: item.quantity,
    location: item.location,
    sku: item.sku,
    cost: item.cost,
    manual_value: item.manual_value,
    notes: item.notes,
    ...patch,
  }
}

/** Quantity, editable in place. Held locally and written on a delay so holding
 *  the + button is one request rather than one per click, and so a refetch
 *  landing mid-edit can't yank the number back to what the server last saw. */
function QuantityCell({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient()
  const [qty, setQty] = useState(item.quantity)
  const dirty = useRef(false)

  useEffect(() => {
    if (!dirty.current) setQty(item.quantity)
  }, [item.quantity])

  useEffect(() => {
    if (!dirty.current || qty === item.quantity) return
    const t = setTimeout(() => {
      apiPut(`/inventory/${item.id}`, itemBody(item, { quantity: qty }))
        .then(() => queryClient.invalidateQueries({ queryKey: ['inventory'] }))
        .finally(() => { dirty.current = false })
    }, 500)
    return () => clearTimeout(t)
  }, [qty, item, queryClient])

  const step = (d: number) => {
    dirty.current = true
    // The column is NOT NULL with a check constraint of > 0; deleting the row is
    // how you get to zero, so the stepper stops at one.
    setQty((q) => Math.max(1, q + d))
  }

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => step(-1)}
        disabled={qty <= 1}
        className="p-1 rounded text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200 disabled:opacity-30"
        aria-label="Decrease quantity"
      >
        <Minus size={12} />
      </button>
      <span className="tabular-nums w-8 text-center">{qty}</span>
      <button
        onClick={() => step(1)}
        className="p-1 rounded text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200"
        aria-label="Increase quantity"
      >
        <Plus size={12} />
      </button>
    </div>
  )
}

/** Condition, editable in place. Changing it changes the row's value, since the
 *  multiplier is applied server-side on read. */
function ConditionCell({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: (condition: string) =>
      apiPut(`/inventory/${item.id}`, itemBody(item, { condition: condition || null })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
  })
  return (
    <select
      value={item.condition ?? ''}
      onChange={(e) => save.mutate(e.target.value)}
      className="bg-transparent text-slate-600 dark:text-neutral-300 text-sm outline-none -ml-1"
    >
      <option value="">—</option>
      {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
    </select>
  )
}

/** The unit value and how much to trust it. A row can be worth nothing knowable
 *  for two quite different reasons, and both are said out loud rather than shown
 *  as a dash that reads like zero. */
function ValueCell({ item, unitOnly = false }: { item: InventoryItem; unitOnly?: boolean }) {
  if (item.value_status === 'no_card') {
    return <span className="text-xs text-slate-400">no price set</span>
  }
  if (item.value_status === 'unresearched') {
    return <span className="text-xs text-slate-400">not priced</span>
  }
  const headline = unitOnly ? item.unit_value : item.total_value
  return (
    <div>
      <div className={`tabular-nums text-slate-800 dark:text-neutral-100 ${unitOnly ? 'text-base font-medium' : ''}`}>
        {formatCurrency(headline ?? 0)}
      </div>
      <div className="text-xs text-slate-400 tabular-nums ml-1">
        {unitOnly
          ? (null)
          : `${formatCurrency(item.unit_value ?? 0)} ea`}
      </div>
    </div>
  )
}

/** Files a row away once its card has been listed, or puts it back.
 *
 *  Not a delete: deleting throws away the condition, location, lot and researched
 *  price, so an ended listing or a mis-click would leave nothing to restore. And
 *  not a "listed" flag either - it records that the row left the pile, and claims
 *  nothing about what is on eBay. */
function ArchiveButton({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient()
  const archived = !!item.archived_at
  const move = useMutation({
    mutationFn: () =>
      apiPost(`/inventory/${item.id}/${archived ? 'unarchive' : 'archive'}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
  })
  const Icon = archived ? ArchiveRestore : Archive
  return (
    <button
      onClick={() => move.mutate()}
      disabled={move.isPending}
      className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200 disabled:opacity-40"
      aria-label={archived ? `Restore ${item.name} to the pile` : `Archive ${item.name}`}
      title={archived ? 'Put back in the pile' : 'Listed it — file this away'}
    >
      {move.isPending ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
    </button>
  )
}

/** Copies a row's fields into a brand new one - a second physical copy of the same
 *  card, or splitting a stack across two locations without retyping everything.
 *  Photos and cost come along; quantity does too, since duplicating a row that says
 *  "3 of these" and then editing one copy down is faster than typing 1 and 2. */
function DuplicateButton({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient()
  const copy = useMutation({
    mutationFn: () => apiPost(`/inventory/${item.id}/duplicate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
  })
  return (
    <button
      onClick={() => copy.mutate()}
      disabled={copy.isPending}
      className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200 disabled:opacity-40"
      aria-label={`Duplicate ${item.name}`}
      title="Duplicate this row"
    >
      {copy.isPending ? <Loader2 size={14} className="animate-spin" /> : <Copy size={14} />}
    </button>
  )
}

/** Delete asks in place instead of through a modal: one row of a long list is a
 *  small enough action that a dialog over the whole page is more interruption
 *  than the decision deserves. */
function DeleteButton({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient()
  const [armed, setArmed] = useState(false)

  // Disarms itself, so a half-pressed delete left on screen doesn't stay live and
  // catch the next click that lands near it.
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])

  const remove = useMutation({
    mutationFn: () => apiDelete(`/inventory/${item.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
  })

  if (armed) {
    return (
      <button
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
        aria-label={`Confirm deleting ${item.name}`}
        className="px-2 py-1 rounded-md text-xs font-medium bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50"
      >
        Confirm
      </button>
    )
  }
  return (
    <button
      onClick={() => setArmed(true)}
      className="p-1.5 rounded-md text-slate-400 hover:text-rose-600 dark:hover:text-rose-400"
      aria-label={`Delete ${item.name}`}
    >
      <Trash2 size={14} />
    </button>
  )
}

/** One item as a card. Read-only by design: the grid is for looking at a pile, and
 *  a select and a stepper on every tile turn browsing into a minefield of accidental
 *  edits. The pencil opens the same dialog the table uses; inline editing stays in
 *  the table, where the controls sit in their own columns.
 *
 *  Memoized: with no pagination the whole pile renders at once, so an unmemoized
 *  tile meant every selection toggle re-rendered every tile (each carrying its own
 *  image, drag state and upload mutation), which locked the tab on large piles.
 *  The callbacks are stable references taking the row as an argument, so only the
 *  toggled tile re-renders on select. Shift-click selects the whole run from the
 *  last-clicked tile (the anchor) to the one shift-clicked, in the current sort
 *  order - the anchor is the tile's position, so re-sorting moves what a later
 *  shift-click covers, the same as any file manager. */
const InventoryCard = memo(function InventoryCard({ item, index, selected, onToggle, onEdit, photoHostingEnabled }: {
  item: InventoryItem
  index: number
  selected: boolean
  onToggle: (id: number, index: number, shiftKey: boolean) => void
  onEdit: (item: InventoryItem) => void
  /** From GET /inventory. False when the server has no Supabase credentials - a
   *  drop is refused with that explanation instead of failing per file. */
  photoHostingEnabled: boolean
}) {
  const queryClient = useQueryClient()
  const [dragging, setDragging] = useState(false)
  const [dropError, setDropError] = useState<string | null>(null)
  // Same nested-enter/leave counting as PhotoUploader: the browser fires
  // dragleave for every child element crossed on the way to the drop target, and
  // a plain boolean would flicker the highlight off mid-drag.
  const dragDepth = useRef(0)

  const upload = useMutation({
    mutationFn: (files: File[]) => uploadPhotos(item.id, files),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
    onError: (e) => setDropError(e instanceof Error ? e.message : 'Upload failed'),
  })

  useEffect(() => {
    if (!dropError) return
    const t = setTimeout(() => setDropError(null), 6000)
    return () => clearTimeout(t)
  }, [dropError])

  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    if (!photoHostingEnabled) return
    dragDepth.current += 1
    setDragging(true)
  }
  const onDragOver = (e: React.DragEvent) => e.preventDefault()
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    if (!photoHostingEnabled) return
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    if (!photoHostingEnabled) {
      setDropError('Photo hosting is off — set it up on Settings first')
      return
    }
    // No type filter, same reasoning as the file picker in PhotoUploader: an
    // extension guess has hidden good files before, and the server decides by
    // decoding the bytes rather than trusting what the browser claims a file is.
    const files = sortByName([...e.dataTransfer.files])
    if (files.length) upload.mutate(files)
  }

  return (
    <GridShell
      selected={selected}
      // Keyboard activation arrives with no event, so shift is simply off there.
      onClick={(e) => onToggle(item.id, index, e?.shiftKey ?? false)}
      label={`Select ${item.name}`}
      dropActive={dragging}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {/* The art, full bleed across the top and the tallest thing on the tile - in
          a grid you recognise a card by its picture, not by reading its name. The
          checkbox rides on top of it so nothing above competes for the space.
          Also the drop target: dragging photo files over the tile anywhere still
          works (the handlers are on GridShell's root), but the overlay reads best
          here, over the biggest thing on the card. */}
      <div className="relative bg-slate-50 dark:bg-neutral-900/40 transition-colors group-hover:bg-slate-100 dark:group-hover:bg-neutral-700">
        <CardArt artUrl={coverArt(item)} className="w-full" fallback="back" />
        {(dragging || upload.isPending) && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-black/50 text-white text-xs font-medium text-center px-2">
            {upload.isPending
              ? <Loader2 size={18} className="animate-spin" />
              : <ImagePlus size={18} />}
            {upload.isPending ? 'Uploading…' : 'Drop to add photos'}
          </div>
        )}
      </div>

      {/* No bottom padding: the action strip below brings its own, and the two
          together left a visible gap under the value. */}
      <div className="flex flex-col gap-1 px-2 pt-2">
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-800 dark:text-neutral-100 truncate" title={item.name}>
            {item.name}
          </div>
          <div className="text-xs text-slate-400 truncate">
            {[
              item.card_query && !item.set_name && !item.number ? `eBay: ${item.card_query}` : item.set_name,
              item.number && `#${item.number}`,
            ].filter(Boolean).join(' · ') || '—'}
          </div>
        </div>

        {/* Set apart from the name above it: the title and its set line are one
            thing to read, the grade and count are another. */}
        <div className="mt-1 flex items-center justify-between gap-2 text-xs">
          <span className="text-slate-600 dark:text-neutral-300 truncate">
            {item.condition || <span className="text-slate-400">—</span>}
          </span>
          <span className="tabular-nums text-slate-500 dark:text-neutral-400 shrink-0">
            ×{item.quantity}
          </span>
        </div>

        {/* Lot and value only. Location is deliberately absent: it is how you FIND a
            card once you have decided on it, which is the table's job, and on a tile it
            competed with the one number worth reading. */}
        {/* Baseline, not items-end: the value is a two-line block whose second line
            comes and goes (each / stated / unfiltered), so aligning bottoms made the
            lot drift up and down between otherwise identical tiles. Baseline pins it
            to the price itself. */}
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-xs text-slate-400 min-w-0 truncate">{item.sku}</div>
          <div className="text-right shrink-0">
            <ValueCell item={item} unitOnly />
          </div>
        </div>
      </div>

      {dropError && (
        <div className="px-2 pt-1 text-[11px] text-rose-600 dark:text-rose-400 truncate" title={dropError}>
          {dropError}
        </div>
      )}

      {/* Actions last, on their own strip: they are what you do to the card once
          you have found it, so they should never be the first thing you land on. */}
      {/* The tile selects; these do their own thing, so the click stops here. */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="mt-auto flex items-center justify-end gap-1 border-t border-slate-100 dark:border-neutral-700 px-1.5 py-1"
      >
        {item.search_url && (
          <a
            href={item.search_url}
            target="_blank"
            rel="noopener noreferrer"
            title="View this search on eBay"
            aria-label={`View the eBay search for ${item.name}`}
            className="p-1.5 rounded-md text-slate-400 hover:text-blue-500"
          >
            <ExternalLink size={14} />
          </a>
        )}
        <ArchiveButton item={item} />
        <DuplicateButton item={item} />
        <button
          onClick={() => onEdit(item)}
          className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200"
          aria-label={`Edit ${item.name}`}
        >
          <Pencil size={14} />
        </button>
        <DeleteButton item={item} />
      </div>
    </GridShell>
  )
})

// One selectable row of the dropdown, flattened so the keyboard doesn't have to
// know that the last one is an action rather than a catalog hit.
type Option =
  | { kind: 'card'; card: CardHit }
  // A free-text eBay search. card_query holds the typed words rather than a
  // catalog identity - which is exactly what the Valuation page's custom search
  // does, and what makes the row priceable at all.
  | { kind: 'search' }
  // No card and no search: the row is worth whatever you say it is worth.
  | { kind: 'stated' }

export function InventoryPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const storageKey = seedKey(user?.id)
  const [editing, setEditing] = useState<InventoryItem | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkEditing, setBulkEditing] = useState(false)
  const [listingCsv, setListingCsv] = useState(false)
  const [prefill, setPrefill] = useState(false)
  const [deleteArmed, setDeleteArmed] = useState(false)

  // --- the always-on card search -------------------------------------------
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CardHit[]>([])
  const [open, setOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const [active, setActive] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  // Applied to every row added from the search. Cataloguing a pile means grading
  // twenty cards from the same lot the same way, so those are set once here
  // rather than re-entered per card.
  const [seedCondition, setSeedCondition] = useState('Near Mint')
  const [seedSku, setSeedSku] = useState('')
  // Which key the current values were restored for. A plain "have we restored yet"
  // boolean is not enough: when the user changes, both effects run in the same
  // commit and the save effect would still hold the previous user's values, writing
  // them under the new user's key.
  const restoredFor = useRef<string | null>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      const d = raw ? JSON.parse(raw) : null
      setSeedCondition(typeof d?.condition === 'string' && CONDITIONS.includes(d.condition) ? d.condition : 'Near Mint')
      setSeedSku(typeof d?.sku === 'string' ? d.sku : '')
    } catch {
      // Hand-edited or unreadable storage should start at the default, not crash.
      setSeedCondition('Near Mint'); setSeedSku('')
    }
    restoredFor.current = storageKey
  }, [storageKey])

  useEffect(() => {
    if (restoredFor.current !== storageKey) return
    try {
      if (seedCondition === 'Near Mint' && !seedSku) localStorage.removeItem(storageKey)
      else localStorage.setItem(storageKey, JSON.stringify({ condition: seedCondition, sku: seedSku }))
    } catch {
      // Quota exceeded or storage blocked (private mode). The page works fine
      // without persistence, so this must not surface as an error.
    }
  }, [seedCondition, seedSku, storageKey])

  // --- filters over what is already stored ---------------------------------
  const [location, setLocation] = useState('')
  const [sku, setSku] = useState('')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [view, chooseView] = useViewPreference('inventory')

  // active | archived. "all" exists on the API but is deliberately not offered
  // here: mixing the two makes the totals mean nothing in particular.
  const [archived, setArchived] = useState<'active' | 'archived'>('active')
  const [sortBy, setSortBy] = useState('type')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 250)
    return () => clearTimeout(t)
  }, [search])

  // Debounced so typing doesn't fire a request per keystroke. The search is a
  // local scan on the server, so this is about request volume, not eBay calls.
  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) { setHits([]); return }
    setSearching(true)
    const t = setTimeout(() => {
      api<CardHit[]>(`/valuation/cards/search?q=${encodeURIComponent(term)}&limit=15`)
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

  const params = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir, archived })
  if (location) params.set('location', location)
  if (sku) params.set('sku', sku)
  if (q) params.set('q', q)
  const queryString = params.toString()

  const { data, isLoading, isError, error } = useQuery<InventoryResponse>({
    queryKey: ['inventory', queryString],
    queryFn: () => api(`/inventory?${queryString}`),
  })

  const items = useMemo(() => data?.items ?? [], [data])
  const totals = data?.totals

  // The real buying lots, not just the ones inventory happens to mention. Without
  // this you can only reuse a SKU already typed against some other row, so the
  // first card off a new lot has to have its SKU remembered by hand.
  const { data: lotsData } = useQuery<LotsResponse>({
    queryKey: ['lots'],
    queryFn: () => api('/lots'),
  })

  const lotOptions = useMemo<LotOption[]>(() => {
    const by = new Map<string, LotOption>()
    // Inventory's own SKUs first so a real lot's entry, which carries a title,
    // overwrites the bare string rather than the other way round. A SKU only
    // inventory knows about still shows up - it is a lot that has no cost entered.
    for (const sku of data?.skus ?? []) by.set(sku, { sku })
    for (const lot of lotsData?.lots ?? []) by.set(lot.sku, { sku: lot.sku, title: lot.title })
    return [...by.values()].sort((a, b) => a.sku.localeCompare(b.sku))
  }, [data?.skus, lotsData])

  // Pricing goes through the Valuation page's own batch endpoint, which reuses
  // today's snapshot when there is one and spends a Browse call only when there
  // isn't. Nothing is stored on the inventory row: the call refreshes the SHARED
  // active_price_snapshots, and this page's own cached read picks the number up on
  // the refetch - so the value still comes from one server-side calculation
  // against each row's own condition, and no price is ever computed here.
  const [priceNote, setPriceNote] = useState<string | null>(null)
  useEffect(() => {
    if (!priceNote) return
    const t = setTimeout(() => setPriceNote(null), 6000)
    return () => clearTimeout(t)
  }, [priceNote])

  const priceCards = useMutation({
    mutationFn: (queries: string[]) =>
      apiPost('/valuation/batch', { card_queries: queries }) as Promise<CardValue[]>,
    onSuccess: (res, queries) => {
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      // Only for a deliberate bulk run. Saying "priced 1 of 1" after every card
      // added would be noise on top of the row that just appeared.
      if (queries.length > 1) {
        const ok = res.filter((v) => v.status === 'ok').length
        const missed = res.length - ok
        setPriceNote(
          missed
            ? `Priced ${ok} of ${res.length}. ${missed} found no usable comps.`
            : `Priced ${ok} ${ok === 1 ? 'card' : 'cards'}.`,
        )
      }
    },
  })

  const add = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPost('/inventory', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
  })

  // Selection is pruned to what is on screen, so a filter change can never leave a
  // row selected that you cannot see - and a bulk action can only ever hit rows you
  // are actually looking at.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev
      const visible = new Set(items.map((i) => i.id))
      const next = new Set([...prev].filter((id) => visible.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [items])

  useEffect(() => { setDeleteArmed(false) }, [selected])

  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id))
  const selectedIds = useMemo(() => [...selected], [selected])

  // The anchor for shift-click range select: the last plain-clicked tile. A ref,
  // not state - moving it must not re-render the grid.
  const anchorRef = useRef<number | null>(null)

  // Stable references so the memoized tiles skip re-rendering: only the tile whose
  // `selected` boolean actually changed does any work on a toggle. Depends on
  // `items` (a shift-click range is positional in the current sort/filter), so a
  // refetch or re-sort mints a new reference - but those already re-render every
  // tile, since each `item` object is new too.
  const handleToggle = useCallback((id: number, index: number, shiftKey: boolean) => {
    if (shiftKey && anchorRef.current != null) {
      const anchorIndex = items.findIndex((i) => i.id === anchorRef.current)
      if (anchorIndex !== -1) {
        // Union, not replace: the anchor stays put, so repeated shift-clicks keep
        // extending from the same tile, and earlier picks outside the run survive.
        const [lo, hi] = anchorIndex < index ? [anchorIndex, index] : [index, anchorIndex]
        const range = items.slice(lo, hi + 1).map((i) => i.id)
        setSelected((prev) => new Set([...prev, ...range]))
        return
      }
    }
    // Plain click (or shift-click with no usable anchor, e.g. the anchor was
    // filtered out of view): toggle one, and it becomes the new anchor.
    anchorRef.current = id
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [items])

  const handleEdit = useCallback((item: InventoryItem) => setEditing(item), [])

  const toggleAll = () => {
    anchorRef.current = null
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))
  }

  const bulkArchive = useMutation({
    mutationFn: () =>
      apiPost('/inventory/bulk-archive', { ids: selectedIds, archived: archived !== 'archived' }),
    onSuccess: () => {
      anchorRef.current = null
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
    },
  })

  const bulkDelete = useMutation({
    mutationFn: () => apiPost('/inventory/bulk-delete', { ids: selectedIds }),
    onSuccess: () => {
      anchorRef.current = null
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
    },
  })

  // Distinct cards with no cached price yet. Rows added before pricing existed, or
  // whose card nothing has ever researched.
  const unpriced = useMemo(() => {
    const seen = new Set<string>()
    for (const i of items) {
      // 'manual' counts as priced: the seller already said what it is worth, and
      // spending an eBay call to contradict them is not what the button is for.
      if (i.card_query && i.value_status !== 'ok' && i.value_status !== 'manual') {
        seen.add(i.card_query)
      }
    }
    return [...seen]
  }, [items])

  // Distinct priceable cards among the current selection - the explicit,
  // user-controlled trigger for a batch of live eBay lookups. Unlike `unpriced`
  // this deliberately includes already-priced rows too: `/valuation/batch` reuses
  // today's snapshot when there is one, so re-running it on a selection is how you
  // ask for a refresh rather than accept a stale number.
  const selectedQueries = useMemo(() => {
    const seen = new Set<string>()
    for (const i of items) {
      if (selected.has(i.id) && i.card_query) seen.add(i.card_query)
    }
    return [...seen]
  }, [items, selected])

  // Added straight away with sensible defaults rather than through a form: the
  // point of a permanent search box is to catalogue a pile at speed, and the row
  // is editable in place the moment it lands.
  function addRow(fields: { name: string; card_query: string | null; set_name: string | null; number: string | null }) {
    add.mutate({
      ...fields,
      condition: seedCondition,
      quantity: 1,
      location: null,
      sku: seedSku.trim() || null,
      cost: null,
      notes: null,
    })
    setQuery(''); setHits([]); setOpen(false)
  }

  const typed = query.trim()
  const options: Option[] = useMemo(() => [
    ...hits.map((card): Option => ({ kind: 'card', card })),
    ...(typed.length >= 2 ? [{ kind: 'search' } as Option, { kind: 'stated' } as Option] : []),
  ], [hits, typed])

  useEffect(() => { setActive(0) }, [options])

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  // finish only means anything for a catalog card - a free-text search or a
  // hand-priced row has no print to distinguish. Defaults to 'regular' so the
  // keyboard flow (Enter) still adds at the same speed as before this existed.
  function choose(i: number, finish: CardFinish = 'regular') {
    const o = options[i]
    if (!o) return
    if (o.kind === 'card') {
      const { card_query, name } = applyFinish(o.card, finish)
      addRow({
        name,
        card_query,
        set_name: o.card.set_name || null,
        number: o.card.number || null,
      })
    } else if (o.kind === 'search') {
      // card_query is the search text. No set or number, which is also how the
      // row is later recognised as a search rather than a catalog card.
      addRow({ name: typed, card_query: typed, set_name: null, number: null })
    } else {
      addRow({ name: typed, card_query: null, set_name: null, number: null })
    }
  }

  const handleSort = (key: string) => {
    if (key === sortBy) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else { setSortBy(key); setSortDir('asc') }
  }

  if (isError) {
    return (
      <div className="text-sm text-rose-600 dark:text-rose-400">
        {(error as Error).message}
      </div>
    )
  }

  if (data && !data.inventory_enabled) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Inventory</h1>
        <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
          <div className="text-sm text-slate-600 dark:text-neutral-300">
            <p className="font-medium text-slate-900 dark:text-neutral-100">Inventory table not created yet</p>
            <p className="mt-1">
              Run <code className="px-1 rounded bg-slate-100 dark:bg-neutral-700">db/migrations/0011_inventory.sql</code>{' '}
              in the Supabase SQL editor, then reload.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Inventory</h1>

      <div className="flex flex-wrap items-start gap-2">
        <div ref={boxRef} className="relative flex-1 min-w-72 max-w-2xl">
          <div className="flex items-center gap-2 bg-white dark:bg-neutral-800 rounded-xl px-3 py-2">
            <Search className="w-4 h-4 text-slate-400 shrink-0" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => hits.length && setOpen(true)}
              onKeyDown={(e) => {
                if (!options.length) return
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                  e.preventDefault()
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
              }}
              role="combobox"
              aria-expanded={open}
              aria-controls="inventory-search-results"
              aria-activedescendant={open ? `inventory-option-${active}` : undefined}
              placeholder="Search a card to add"
              className="w-full bg-transparent outline-none text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400"
            />
            {(searching || add.isPending) && <Loader2 className="w-4 h-4 animate-spin text-slate-400 shrink-0" />}
          </div>

          {open && options.length > 0 && (
            <ul
              ref={listRef}
              id="inventory-search-results"
              role="listbox"
              className="absolute z-20 mt-1 w-full max-h-80 overflow-y-auto bg-white dark:bg-neutral-800 rounded-xl shadow-lg ring-1 ring-black/5 dark:ring-white/10"
            >
              {hits.map((h, i) => (
                <li key={h.card_query + h.number} className={`flex items-center ${active === i ? HIGHLIGHT : ''}`}>
                  <button
                    id={`inventory-option-${i}`}
                    data-idx={i}
                    role="option"
                    aria-selected={active === i}
                    // Hovering moves the highlight instead of drawing a second one,
                    // so the mouse and the arrow keys can never disagree about what
                    // Enter will add.
                    onMouseEnter={() => setActive(i)}
                    onClick={() => choose(i)}
                    title={`Add as ${finishLabel('regular')}`}
                    className="min-w-0 flex-1 text-left px-3 py-2"
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
                  {/* Regular is the row's own click target above (and what Enter
                      adds); these two cover the other prints of the same catalogued
                      card. Only Reverse Holo changes what gets priced - see
                      lib/cardFinish.ts for why Non-Holo doesn't. */}
                  <CardFinishButtons setName={h.set_name} onPick={(finish) => choose(i, finish)} />
                </li>
              ))}
              {typed.length >= 2 && (
                <li className={hits.length ? 'border-t border-slate-100 dark:border-neutral-700' : undefined}>
                  <button
                    id={`inventory-option-${hits.length}`}
                    data-idx={hits.length}
                    role="option"
                    aria-selected={active === hits.length}
                    onMouseEnter={() => setActive(hits.length)}
                    onClick={() => choose(hits.length)}
                    className={`w-full text-left px-3 py-2 ${active === hits.length ? HIGHLIGHT : ''}`}
                  >
                    <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                      <Search className="w-3.5 h-3.5" />
                      Price <span className="font-medium text-slate-900 dark:text-neutral-100">"{typed}"</span> from an eBay search
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
              {typed.length >= 2 && (
                <li className="border-t border-slate-100 dark:border-neutral-700">
                  <button
                    id={`inventory-option-${hits.length + 1}`}
                    data-idx={hits.length + 1}
                    role="option"
                    aria-selected={active === hits.length + 1}
                    onMouseEnter={() => setActive(hits.length + 1)}
                    onClick={() => choose(hits.length + 1)}
                    className={`w-full text-left px-3 py-2 ${active === hits.length + 1 ? HIGHLIGHT : ''}`}
                  >
                    <span className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-neutral-300">
                      <Pencil className="w-3.5 h-3.5" />
                      Add <span className="font-medium text-slate-900 dark:text-neutral-100">"{typed}"</span> and price it myself
                    </span>
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>

        {/* Stamped onto whatever the search adds next. Kept beside the box rather
            than inside the dropdown so it is visible while adding, not a setting
            to remember. Ringed while set to something other than the default,
            because these now outlive the page and a value carried over from days
            ago should not be easy to miss. */}
        <select
          value={seedCondition}
          onChange={(e) => setSeedCondition(e.target.value)}
          className={`${SEED_FIELD} ${seedCondition !== 'Near Mint' ? SEED_ACTIVE : ''}`}
        >
          {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          value={seedSku}
          onChange={(e) => setSeedSku(e.target.value)}
          list="inventory-skus"
          maxLength={40}
          placeholder="Lot"
          className={`${SEED_FIELD} w-24 ${seedSku ? SEED_ACTIVE : ''}`}
        />
        {(seedCondition !== 'Near Mint' || seedSku) && (
          <button
            onClick={() => { setSeedCondition('Near Mint'); setSeedSku('') }}
            className="text-xs text-slate-500 dark:text-neutral-400 hover:text-slate-800 dark:hover:text-neutral-200 self-center"
          >
            Clear
          </button>
        )}
        <datalist id="inventory-skus">
          {lotOptions.map((l) => <option key={l.sku} value={l.sku}>{l.title || undefined}</option>)}
        </datalist>
      </div>

      {add.isError && (
        <p className="text-xs text-rose-600 dark:text-rose-400">{(add.error as Error).message}</p>
      )}

      {isLoading || !totals ? (
        <KpiSkeleton />
      ) : (
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <KpiCard title="Entries" value={formatInt(totals.entries)} />
          <KpiCard title="Cards" value={formatInt(totals.units)} />
          <KpiCard
            title="Est. Value"
            // The coverage rides along in the value, because the total only covers
            // entries that have a cached price - reading it as the whole pile's
            // worth would overstate a mostly-unpriced list.
            value={
              totals.valued_entries === totals.entries
                ? formatCurrency(totals.value)
                : `${formatCurrency(totals.value)} (${totals.valued_entries}/${totals.entries})`
            }
          />
          <KpiCard title="Cost" value={formatCurrency(totals.cost)} />
        </div>
      )}

      {/* Pricing the backlog is an explicit action with a visible count, never
          something the page does on load: each uncached card is a live Browse call,
          and a pile can hold hundreds. The cap is the server's own. */}
      {(unpriced.length > 0 || priceNote) && (
        <div className="flex flex-wrap items-center gap-3 bg-white dark:bg-neutral-800 rounded-xl px-4 py-3">
          {unpriced.length > 0 && (
            <>
              <span className="text-sm text-slate-600 dark:text-neutral-300">
                {unpriced.length} {unpriced.length === 1 ? 'card has' : 'cards have'} no price yet
              </span>
              <button
                onClick={() => priceCards.mutate(unpriced.slice(0, MAX_PRICE_BATCH))}
                disabled={priceCards.isPending}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {priceCards.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Sparkles size={14} />}
                Price {Math.min(unpriced.length, MAX_PRICE_BATCH)}
              </button>
              {unpriced.length > MAX_PRICE_BATCH && (
                <span className="text-xs text-slate-400">
                  {MAX_PRICE_BATCH} at a time — each one is a live eBay lookup
                </span>
              )}
            </>
          )}
          {priceNote && (
            <span className="text-xs text-slate-500 dark:text-neutral-400">{priceNote}</span>
          )}
        </div>
      )}

      {priceCards.isError && (
        <p className="text-xs text-rose-600 dark:text-rose-400">{(priceCards.error as Error).message}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 bg-white dark:bg-neutral-800 rounded-lg px-3 py-2 min-w-56">
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter name or notes"
            className="w-full bg-transparent outline-none text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400"
          />
        </div>
        <select className={SELECT} value={location} onChange={(e) => setLocation(e.target.value)}>
          <option value="">All locations</option>
          {(data?.locations ?? []).map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <select
          className={SELECT}
          value={archived}
          onChange={(e) => setArchived(e.target.value as 'active' | 'archived')}
        >
          <option value="active">In the pile</option>
          <option value="archived">Archived</option>
        </select>
        <select className={SELECT} value={sku} onChange={(e) => setSku(e.target.value)}>
          <option value="">All lots</option>
          {(data?.skus ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* The grid has no column headers to click, so select-all needs an explicit
            control here. The table has no header checkbox either - a row click
            already means "select this" there - so this one isn't view-gated. */}
        {items.length > 0 && (
          <button
            onClick={toggleAll}
            className="px-3 py-2 text-sm text-slate-600 dark:text-neutral-300 hover:text-slate-900 dark:hover:text-neutral-100"
          >
            {allSelected ? 'Deselect all' : 'Select all'}
          </button>
        )}
        {view === 'grid' && items.length > 1 && (
          <span className="text-xs text-slate-400">Shift-click selects a range</span>
        )}

        {/* Same reasoning for sort: the table's column headers cover most of these
            keys, but "Card #" has no column of its own to click, so this control
            stays visible in both views rather than only where headers are absent. */}
        <select
          className={SELECT}
          value={`${sortBy}:${sortDir}`}
          onChange={(e) => {
            const [key, dir] = e.target.value.split(':')
            setSortBy(key)
            setSortDir(dir as 'asc' | 'desc')
          }}
        >
          {SORTS.flatMap((o) => [
            <option key={`${o.key}:asc`} value={`${o.key}:asc`}>{o.label} ↑</option>,
            <option key={`${o.key}:desc`} value={`${o.key}:desc`}>{o.label} ↓</option>,
          ])}
        </select>

        <div className="ml-auto">
          <ViewToggle view={view} onChange={chooseView} />
        </div>
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 bg-white dark:bg-neutral-800 rounded-xl px-4 py-3">
          <span className="text-sm font-medium text-slate-700 dark:text-neutral-200">
            {selected.size} selected
          </span>
          {/* Pricing is never automatic - adding a card to the pile no longer
              spends an eBay call on its own. This is the one deliberate trigger for
              the current selection, capped the same way the backlog button is. */}
          {selectedQueries.length > 0 && (
            <button
              onClick={() => priceCards.mutate(selectedQueries.slice(0, MAX_PRICE_BATCH))}
              disabled={priceCards.isPending}
              title={
                selectedQueries.length > MAX_PRICE_BATCH
                  ? `Prices the first ${MAX_PRICE_BATCH} of ${selectedQueries.length} distinct cards selected`
                  : undefined
              }
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {priceCards.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <Sparkles size={14} />}
              Price {Math.min(selectedQueries.length, MAX_PRICE_BATCH)}
            </button>
          )}
          <button
            onClick={() => bulkArchive.mutate()}
            disabled={bulkArchive.isPending}
            className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200 disabled:opacity-50"
          >
            {bulkArchive.isPending
              ? <Loader2 size={14} className="animate-spin" />
              : (archived === 'archived' ? <ArchiveRestore size={14} /> : <Archive size={14} />)}
            {archived === 'archived' ? 'Restore' : 'Archive'}
          </button>
          <button
            onClick={() => setBulkEditing(true)}
            className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200"
          >
            <Pencil size={14} />
            Edit
          </button>
          {/* Builds the eBay bulk-upload file for these rows. Nothing is sent to
              eBay from here - the dialog shows every title and price first, and the
              seller uploads the file themselves. */}
          <button
            onClick={() => setListingCsv(true)}
            className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200"
          >
            <FileSpreadsheet size={14} />
            Listing CSV
          </button>
          {/* The other route to a listing: eBay's three-step prefill round trip,
              where it suggests the category, title and aspects rather than this app
              deciding them. Fills the template you downloaded from Seller Hub. */}
          <button
            onClick={() => setPrefill(true)}
            className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200"
          >
            <FileUp size={14} />
            Prefill template
          </button>
          {/* Two-step, like the per-row delete, but this one says the count out
              loud - the whole risk of a bulk action is not knowing its size. */}
          {deleteArmed ? (
            <button
              onClick={() => bulkDelete.mutate()}
              disabled={bulkDelete.isPending}
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-rose-600 text-white text-sm font-medium rounded-lg hover:bg-rose-700 disabled:opacity-50"
            >
              {bulkDelete.isPending && <Loader2 size={14} className="animate-spin" />}
              Delete {selected.size} — confirm
            </button>
          ) : (
            <button
              onClick={() => setDeleteArmed(true)}
              className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200 hover:text-rose-600 dark:hover:text-rose-400"
            >
              <Trash2 size={14} />
              Delete
            </button>
          )}
          <button
            onClick={() => { anchorRef.current = null; setSelected(new Set()) }}
            className="text-xs text-slate-500 dark:text-neutral-400 hover:text-slate-800 dark:hover:text-neutral-200"
          >
            Clear selection
          </button>
          {bulkDelete.isError && (
            <span className="text-xs text-rose-600 dark:text-rose-400">
              {(bulkDelete.error as Error).message}
            </span>
          )}
        </div>
      )}

      {isLoading ? (
        <TableSkeleton />
      ) : view === 'grid' ? (
        items.length === 0 ? (
          <div className="bg-white dark:bg-neutral-800 rounded-xl p-8 text-center text-slate-400 text-sm">
            No data
          </div>
        ) : (
          <div className={GRID_CLASS}>
            {items.map((item, index) => (
              <InventoryCard
                key={item.id}
                item={item}
                index={index}
                selected={selected.has(item.id)}
                onToggle={handleToggle}
                onEdit={handleEdit}
                photoHostingEnabled={data?.photo_hosting_enabled ?? false}
              />
            ))}
          </div>
        )
      ) : (
        <DataTable<InventoryItem & Record<string, unknown>>
          columns={[
            {
              key: 'name',
              header: 'Item',
              sortKey: 'name',
              render: (r) => (
                <div className="flex items-center gap-3">
                  <CardArt artUrl={coverArt(r)} className="w-16 rounded" fallback="back" />
                  <div className="min-w-0">
                    <div className="font-medium text-slate-800 dark:text-neutral-100 truncate">{r.name}</div>
                    <div className="text-xs text-slate-400 truncate">
                      {/* A row whose card_query carries no set or number is a
                          free-text eBay search, so show the words being searched -
                          they are what the price came from. */}
                      {[
                        r.card_query && !r.set_name && !r.number ? `eBay: ${r.card_query}` : r.set_name,
                        r.number && `#${r.number}`,
                        r.notes,
                      ].filter(Boolean).join(' · ') || '—'}
                    </div>
                  </div>
                </div>
              ),
            },
            {
              key: 'condition',
              header: 'Condition',
              sortKey: 'condition',
              className: 'w-40',
              stopRowClick: true,
              render: (r) => <ConditionCell item={r} />,
            },
            {
              key: 'quantity',
              header: 'Qty',
              sortKey: 'quantity',
              className: 'w-24',
              stopRowClick: true,
              render: (r) => <QuantityCell item={r} />,
            },
            {
              key: 'location',
              header: 'Location',
              sortKey: 'location',
              className: 'w-40',
              render: (r) => (
                <span className="text-slate-600 dark:text-neutral-300">
                  {r.location || <span className="text-slate-400">—</span>}
                </span>
              ),
            },
            {
              key: 'sku',
              header: 'Lot',
              sortKey: 'sku',
              className: 'w-24',
              render: (r) => (
                <span className="text-slate-600 dark:text-neutral-300">
                  {r.sku || <span className="text-slate-400">—</span>}
                </span>
              ),
            },
            {
              key: 'cost',
              header: 'Cost',
              sortKey: 'cost',
              className: 'w-24',
              render: (r) => (
                r.total_cost == null
                  ? <span className="text-slate-400 text-xs">—</span>
                  : (
                    <div>
                      <div className="tabular-nums text-slate-800 dark:text-neutral-100">
                        {formatCurrency(r.total_cost)}
                      </div>
                      {r.quantity > 1 && (
                        <div className="text-xs text-slate-400 tabular-nums">
                          {formatCurrency(r.cost ?? 0)} ea
                        </div>
                      )}
                    </div>
                  )
              ),
            },
            {
              key: 'value',
              header: 'Est. Value',
              className: 'w-28',
              render: (r) => <ValueCell item={r} />,
            },
            {
              key: 'actions',
              header: '',
              className: 'w-32',
              stopRowClick: true,
              render: (r) => (
                <div className="flex items-center justify-end gap-1">
                  {/* Shown for a stated-price row too, where the pool is not what
                      the row is priced from but is still the quickest way to check
                      the number against the market. */}
                  {r.search_url && (
                    <a
                      href={r.search_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="View this search on eBay"
                      aria-label={`View the eBay search for ${r.name}`}
                      className="p-1.5 rounded-md text-slate-400 hover:text-blue-500"
                    >
                      <ExternalLink size={14} />
                    </a>
                  )}
                  <ArchiveButton item={r} />
                  <DuplicateButton item={r} />
                  <button
                    onClick={() => setEditing(r)}
                    className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200"
                    aria-label={`Edit ${r.name}`}
                  >
                    <Pencil size={14} />
                  </button>
                  <DeleteButton item={r} />
                </div>
              ),
            },
          ]}
          data={items as (InventoryItem & Record<string, unknown>)[]}
          keyField="id"
          // Clicking a row picks it. Columns that carry their own controls -
          // condition, quantity, the action buttons - are marked stopRowClick, so
          // changing a grade does not also toggle the selection under it.
          onRowClick={(r) => handleToggle(r.id, items.findIndex((i) => i.id === r.id), false)}
          isRowSelected={(r) => selected.has(r.id)}
          sortBy={sortBy}
          sortDir={sortDir}
          onSortChange={handleSort}
        />
      )}

      {listingCsv && (
        <InventoryListingCsvDialog ids={selectedIds} onClose={() => setListingCsv(false)} />
      )}

      {prefill && (
        <InventoryPrefillDialog ids={selectedIds} onClose={() => setPrefill(false)} />
      )}

      {bulkEditing && (
        <InventoryBulkDialog
          ids={selectedIds}
          locations={data?.locations ?? []}
          skus={lotOptions}
          onClose={() => setBulkEditing(false)}
        />
      )}

      {editing && (
        <InventoryEditDialog
          item={editing}
          locations={data?.locations ?? []}
          skus={lotOptions}
          photoHostingEnabled={data?.photo_hosting_enabled ?? false}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
