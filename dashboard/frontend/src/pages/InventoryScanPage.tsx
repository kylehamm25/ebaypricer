import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowLeftRight, Check, ImagePlus, Loader2, RefreshCw, ScanLine, Trash2, Undo2,
} from 'lucide-react'
import { api, apiPost, apiUpload } from '../lib/api'
import { CardArt } from '../components/shared/ViewToggle'
import { CardFinishButtons } from '../components/shared/CardFinishButtons'
import { CardSearch } from '../components/shared/CardSearch'
import { CONDITIONS } from '../lib/conditions'
import { sortByName } from '../lib/photos'
import { applyFinish, finishLabel, finishesFor } from '../lib/cardFinish'
import type { CardFinish } from '../lib/cardFinish'
import type {
  CardHit, CardValue, ImportCandidate, InventoryImport, InventoryImportsResponse, LotOption, LotsResponse,
} from '../types'

const IMPORT_KEY = ['inventory-imports'] as const
const MAX_PRICE_BATCH = 25
// The server reads one card at a time but resizes/uploads the next in parallel, so
// keeping an extra card in flight stops the recognizer from waiting between photos.
const UPLOAD_CONCURRENCY = 3
const MAX_SCAN_CARDS = 50
const MAX_SCAN_IMAGES = MAX_SCAN_CARDS * 2
const SEED_FINISHES: CardFinish[] = ['regular', 'reverse', 'non_holo']
const SIDE_MIME = 'application/x-scan-side'

const hasFiles = (e: DragEvent<HTMLElement>) =>
  Array.from(e.dataTransfer.types).includes('Files')

function newJobId(): string {
  return typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

const FIELD =
  'bg-white dark:bg-neutral-900 border border-slate-300 dark:border-neutral-600 text-slate-700 ' +
  'dark:text-neutral-100 placeholder:text-slate-400 rounded-lg px-3 py-2 text-sm outline-none'

type ScanJob = {
  id: string
  front: File
  back?: File
  preview: string
  backPreview?: string
  status: 'queued' | 'uploading' | 'error'
  message?: string
}

type ConfirmVars = {
  id: number
  body: Record<string, unknown>
  auto: boolean
  priceQuery?: string
}

function confidenceTone(confidence: InventoryImport['confidence']): string {
  if (confidence === 'high') return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
  if (confidence === 'medium') return 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'
  if (confidence === 'low') return 'bg-slate-100 text-slate-600 dark:bg-neutral-700 dark:text-neutral-300'
  return 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300'
}

function candidateName(item: InventoryImport): string {
  return item.candidates[0]?.name || item.detected_name || item.source_filename || 'Scanned card'
}

function emptyImports(): InventoryImportsResponse {
  return {
    pending: [],
    recent: [],
    imports_enabled: true,
    photo_hosting_enabled: true,
    recognition_enabled: true,
  }
}

export function InventoryScanPage() {
  const queryClient = useQueryClient()
  const [condition, setCondition] = useState('Near Mint')
  const [finish, setFinish] = useState<CardFinish>('regular')
  const [location, setLocation] = useState('')
  const [sku, setSku] = useState('')
  const [queue, setQueue] = useState<ScanJob[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [bulkAction, setBulkAction] = useState<'adding' | 'removing' | null>(null)
  const [removeAllArmed, setRemoveAllArmed] = useState(false)
  const [isScanningDropActive, setIsScanningDropActive] = useState(false)
  const scanDragDepth = useRef(0)
  const activeUploads = useRef(0)
  const autoTried = useRef(new Set<number>())
  const pricedQueries = useRef(new Set<string>())
  const libraryRef = useRef<HTMLInputElement>(null)

  const { data, isLoading, isError, error } = useQuery<InventoryImportsResponse>({
    queryKey: IMPORT_KEY,
    queryFn: () => api('/inventory/imports'),
  })
  const { data: lotsData } = useQuery<LotsResponse>({
    queryKey: ['lots'],
    queryFn: () => api('/lots'),
  })

  const pending = data?.pending ?? []
  const recent = data?.recent ?? []
  const canScan = Boolean(
    data?.imports_enabled && data.photo_hosting_enabled && data.recognition_enabled,
  )
  const lotOptions = lotsData?.lots ?? []

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 8000)
    return () => clearTimeout(t)
  }, [notice])

  useEffect(() => {
    if (!removeAllArmed) return
    const t = setTimeout(() => setRemoveAllArmed(false), 4000)
    return () => clearTimeout(t)
  }, [removeAllArmed])

  const startPrice = useMutation({
    mutationFn: (query: string) =>
      apiPost('/valuation/batch', { card_queries: [query] }) as Promise<CardValue[]>,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['inventory'] }),
    onError: (e) => setNotice(`Added, but pricing did not run: ${(e as Error).message}`),
  })

  const confirm = useMutation({
    mutationFn: (vars: ConfirmVars) =>
      apiPost(`/inventory/imports/${vars.id}/confirm`, vars.body) as Promise<{
        status: string
        id: number
        inventory_id: number
      }>,
    onSuccess: (res, vars) => {
      queryClient.setQueryData<InventoryImportsResponse>(IMPORT_KEY, (old) => {
        if (!old) return old
        const found = old.pending.find((item) => item.id === vars.id)
        const confirmed = found
          ? {
              ...found,
              status: 'confirmed' as const,
              auto_added: vars.auto,
              inventory_id: res.inventory_id,
              chosen_card_query: (vars.body.card_query as string | null | undefined) ?? null,
            }
          : null
        return {
          ...old,
          pending: old.pending.filter((item) => item.id !== vars.id),
          recent: vars.auto && confirmed
            ? [confirmed, ...old.recent.filter((item) => item.id !== vars.id)].slice(0, 20)
            : old.recent,
        }
      })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      if (vars.priceQuery) {
        if (pricedQueries.current.has(vars.priceQuery)) return
        if (pricedQueries.current.size >= MAX_PRICE_BATCH) {
          setNotice(`Added ${vars.body.name}. Price the rest from Inventory - this batch is at ${MAX_PRICE_BATCH}.`)
          return
        }
        pricedQueries.current.add(vars.priceQuery)
        startPrice.mutate(vars.priceQuery)
      }
    },
    onError: (e, vars) => {
      setNotice(`${vars.auto ? 'Could not auto-add that card' : 'Could not add that card'}: ${(e as Error).message}`)
    },
  })

  const dismiss = useMutation({
    mutationFn: (id: number) => apiPost(`/inventory/imports/${id}/dismiss`),
    onSuccess: (_res, id) => {
      queryClient.setQueryData<InventoryImportsResponse>(IMPORT_KEY, (old) => old
        ? { ...old, pending: old.pending.filter((item) => item.id !== id) }
        : old)
    },
    onError: (e) => setNotice(`Could not dismiss that scan: ${(e as Error).message}`),
  })

  const rescan = useMutation({
    mutationFn: (id: number) =>
      apiPost(`/inventory/imports/${id}/rescan`) as Promise<InventoryImport>,
    onSuccess: (updated) => {
      queryClient.setQueryData<InventoryImportsResponse>(IMPORT_KEY, (old) => old
        ? { ...old, pending: old.pending.map((item) => item.id === updated.id ? updated : item) }
        : old)
    },
    onError: (e) => setNotice(`Could not rescan that card: ${(e as Error).message}`),
  })

  const undo = useMutation({
    mutationFn: (id: number) => apiPost(`/inventory/imports/${id}/undo`),
    onSuccess: (_res, id) => {
      queryClient.setQueryData<InventoryImportsResponse>(IMPORT_KEY, (old) => old
        ? { ...old, recent: old.recent.filter((item) => item.id !== id) }
        : old)
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
    },
    onError: (e) => setNotice(`Could not undo that add: ${(e as Error).message}`),
  })

  const addAllPending = async () => {
    if (!pending.length || bulkAction) return
    setBulkAction('adding')
    const appliedFinish: CardFinish = finish
    let unmatched = 0
    try {
      for (const item of pending) {
        const chosen = item.candidates[0]
        if (!chosen) {
          unmatched += 1
          continue
        }
        const applied = applyFinish({ card_query: chosen.card_query, name: chosen.name }, appliedFinish)
        try {
          await confirm.mutateAsync({
            id: item.id,
            auto: false,
            body: {
              card_query: applied.card_query || null,
              name: applied.name.trim(),
              condition: condition || null,
              quantity: 1,
              location: location.trim() || null,
              sku: sku.trim() || null,
              auto: false,
            },
            priceQuery: applied.card_query || undefined,
          })
        } catch {
          unmatched += 1
        }
      }
    } finally {
      setBulkAction(null)
    }
    if (unmatched > 0) {
      setNotice(`${unmatched} scan${unmatched === 1 ? '' : 's'} still need${unmatched === 1 ? 's' : ''} a match before it can be added.`)
    }
  }

  const removeAllPending = async () => {
    if (!pending.length || bulkAction) return
    setBulkAction('removing')
    try {
      for (const item of pending) {
        try {
          await dismiss.mutateAsync(item.id)
        } catch {
          // dismiss.onError already surfaced the failure
        }
      }
    } finally {
      setBulkAction(null)
      setRemoveAllArmed(false)
    }
  }

  const runScan = useCallback(async (job: ScanJob) => {
    try {
      const imported = await apiUpload<InventoryImport>(
        '/inventory/imports/scan',
        job.front,
        'file',
        job.back ? { back: job.back } : undefined,
      )
      queryClient.setQueryData<InventoryImportsResponse>(IMPORT_KEY, (old) => {
        const base = old ?? emptyImports()
        return {
          ...base,
          pending: [imported, ...base.pending.filter((item) => item.id !== imported.id)],
        }
      })
      setQueue((q) => q.filter((j) => j.id !== job.id))
      URL.revokeObjectURL(job.preview)
      if (job.backPreview) URL.revokeObjectURL(job.backPreview)

      if (imported.auto_add_eligible && !autoTried.current.has(imported.id)) {
        autoTried.current.add(imported.id)
        const hit = imported.candidates[0]
        if (hit) {
          const applied = applyFinish({ card_query: hit.card_query, name: hit.name }, finish)
          confirm.mutate({
            id: imported.id,
            auto: true,
            priceQuery: applied.card_query,
            body: {
              card_query: applied.card_query,
              name: applied.name,
              condition,
              quantity: 1,
              location: location.trim() || null,
              sku: sku.trim() || null,
              auto: true,
            },
          })
        }
      }
    } catch (e) {
      setQueue((q) => q.map((j) => j.id === job.id
        ? { ...j, status: 'error', message: (e as Error).message }
        : j))
    }
  }, [condition, confirm, finish, location, queryClient, sku])

  useEffect(() => {
    if (!canScan || activeUploads.current >= UPLOAD_CONCURRENCY) return
    const next = queue.find((job) => job.status === 'queued')
    if (!next) return

    activeUploads.current += 1
    setQueue((q) => q.map((job) => job.id === next.id ? { ...job, status: 'uploading' } : job))
    void runScan(next).finally(() => {
      activeUploads.current -= 1
      // Nudge the effect so the next queued photo starts as soon as a slot frees.
      setQueue((q) => [...q])
    })
  }, [canScan, queue, runScan])

  function enqueue(files: File[]) {
    if (!canScan) {
      setNotice('Scanning is not available until the setup notes above are resolved.')
      return
    }
    if (files.length > MAX_SCAN_IMAGES) {
      setNotice(`The scan page takes up to ${MAX_SCAN_CARDS} cards (${MAX_SCAN_IMAGES} photos) at a time.`)
    }
    const ordered = sortByName(files).slice(0, MAX_SCAN_IMAGES)
    if (!ordered.length) return
    const jobs: ScanJob[] = []
    for (let i = 0; i < ordered.length; i += 2) {
      const front = ordered[i]
      const back = ordered[i + 1]
      jobs.push({
        id: newJobId(),
        front,
        back,
        preview: URL.createObjectURL(front),
        backPreview: back ? URL.createObjectURL(back) : undefined,
        status: 'queued',
      })
    }
    setQueue((q) => [...q, ...jobs])
  }

  function onFilesPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    enqueue(files)
  }

  const onScanDragEnter = (e: DragEvent<HTMLElement>) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    if (!canScan) return
    scanDragDepth.current += 1
    setIsScanningDropActive(true)
  }

  const onScanDragOver = (e: DragEvent<HTMLElement>) => {
    if (!hasFiles(e)) return
    e.preventDefault()
  }

  const onScanDragLeave = (e: DragEvent<HTMLElement>) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    if (!canScan) return
    scanDragDepth.current = Math.max(0, scanDragDepth.current - 1)
    if (scanDragDepth.current === 0) setIsScanningDropActive(false)
  }

  const onScanDrop = (e: DragEvent<HTMLElement>) => {
    if (!hasFiles(e)) return
    e.preventDefault()
    scanDragDepth.current = 0
    setIsScanningDropActive(false)
    if (!canScan) {
      setNotice('Scanning is not available until the setup notes above are resolved.')
      return
    }
    enqueue(Array.from(e.dataTransfer.files ?? []))
  }

  function removeQueued(job: ScanJob) {
    URL.revokeObjectURL(job.preview)
    if (job.backPreview) URL.revokeObjectURL(job.backPreview)
    setQueue((q) => q.filter((item) => item.id !== job.id))
  }

  function swapSides(jobId: string) {
    setQueue((q) => q.map((j) =>
      j.id === jobId && j.back && j.backPreview && j.status === 'queued'
        ? { ...j, front: j.back, back: j.front, preview: j.backPreview, backPreview: j.preview }
        : j))
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <Link to="/inventory" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 dark:text-neutral-400 dark:hover:text-neutral-200">
          <ArrowLeft size={16} /> Inventory
        </Link>
        <p className="text-sm text-rose-600 dark:text-rose-400">{(error as Error).message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Link to="/inventory" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 dark:text-neutral-400 dark:hover:text-neutral-200">
        <ArrowLeft size={16} /> Inventory
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Scan cards</h1>
        </div>
        {pending.length > 0 && (
          <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
            {pending.length} to review
          </span>
        )}
      </div>

      {data && !data.imports_enabled && (
        <div className="flex items-start gap-3 rounded-xl bg-white dark:bg-neutral-800 p-4">
          <ScanLine size={18} className="mt-0.5 shrink-0 text-amber-500" />
          <div className="text-sm text-slate-600 dark:text-neutral-300">
            <p className="font-medium text-slate-900 dark:text-neutral-100">Scan queue not created yet</p>
            <p className="mt-1">
              Run <code className="rounded bg-slate-100 px-1 dark:bg-neutral-700">db/migrations/0021_inventory_imports.sql</code>{' '}
              in the Supabase SQL editor, then reload.
            </p>
          </div>
        </div>
      )}

      {data && !data.photo_hosting_enabled && (
        <div className="flex items-start gap-3 rounded-xl bg-white dark:bg-neutral-800 p-4">
          <ImagePlus size={18} className="mt-0.5 shrink-0 text-amber-500" />
          <div className="text-sm text-slate-600 dark:text-neutral-300">
            <p className="font-medium text-slate-900 dark:text-neutral-100">Photo hosting is off</p>
            <p className="mt-1">
              Scanning needs somewhere to keep the photo for the inventory row and the listing.
              Set up Supabase storage on <Link to="/settings" className="text-blue-600 hover:underline dark:text-blue-400">Settings</Link>.
            </p>
          </div>
        </div>
      )}

      {data && !data.recognition_enabled && (
        <div className="flex items-start gap-3 rounded-xl bg-white dark:bg-neutral-800 p-4">
          <ScanLine size={18} className="mt-0.5 shrink-0 text-amber-500" />
          <div className="text-sm text-slate-600 dark:text-neutral-300">
            <p className="font-medium text-slate-900 dark:text-neutral-100">Recognition is not installed</p>
            <p className="mt-1">
              Install <code className="rounded bg-slate-100 px-1 dark:bg-neutral-700">requirements-dashboard.txt</code>{' '}
              and restart the backend. Until then you can still add cards from Inventory.
            </p>
          </div>
        </div>
      )}

      <section
        className={`rounded-xl bg-white p-4 dark:bg-neutral-800 ${
          isScanningDropActive ? 'ring-2 ring-blue-500/60 bg-blue-50/50 dark:bg-blue-500/10' : ''
        }`}
        onDragEnter={onScanDragEnter}
        onDragOver={onScanDragOver}
        onDragLeave={onScanDragLeave}
        onDrop={onScanDrop}
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => libraryRef.current?.click()}
            disabled={!canScan}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-200 dark:hover:bg-neutral-700"
          >
            <ImagePlus size={16} /> Choose photos
          </button>
          <input
            ref={libraryRef}
            type="file"
            multiple
            className="hidden"
            onChange={onFilesPicked}
          />
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-slate-100 pt-4 dark:border-neutral-700">
          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Condition</span>
            <select className={`${FIELD} mt-1 block`} value={condition} onChange={(e) => setCondition(e.target.value)}>
              {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Finish</span>
            <select className={`${FIELD} mt-1 block`} value={finish} onChange={(e) => setFinish(e.target.value as CardFinish)}>
              {SEED_FINISHES.map((f) => <option key={f} value={f}>{finishLabel(f)}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Lot</span>
            <input
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              list="scan-lots"
              maxLength={40}
              placeholder="L0042"
              className={`${FIELD} mt-1 block w-32`}
            />
            <datalist id="scan-lots">
              {lotOptions.map((lot: LotOption) => (
                <option key={lot.sku} value={lot.sku}>{lot.title || undefined}</option>
              ))}
            </datalist>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Location</span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              maxLength={120}
              placeholder="Box 3 / Binder A"
              className={`${FIELD} mt-1 block w-40`}
            />
          </label>
        </div>

        {queue.length > 0 && (
          <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 dark:border-neutral-700">
            {queue.map((job) => (
              <div key={job.id} className="flex items-center gap-3 rounded-lg bg-slate-50 p-2 dark:bg-neutral-900/40">
                <div className="flex shrink-0 items-center gap-1">
                  {(['front', 'back'] as const).map((side) => {
                    const src = side === 'front' ? job.preview : job.backPreview
                    if (!src) return null
                    const swappable = Boolean(job.back) && job.status === 'queued'
                    return (
                      <div
                        key={side}
                        className={`relative ${swappable ? 'cursor-grab active:cursor-grabbing' : ''}`}
                        draggable={swappable}
                        onDragStart={(e) => {
                          e.dataTransfer.setData(SIDE_MIME, `${job.id}:${side}`)
                          e.dataTransfer.effectAllowed = 'move'
                        }}
                        onDragOver={(e) => {
                          if (swappable && e.dataTransfer.types.includes(SIDE_MIME)) {
                            e.preventDefault()
                            e.dataTransfer.dropEffect = 'move'
                          }
                        }}
                        onDrop={(e) => {
                          const [fromId, fromSide] = e.dataTransfer.getData(SIDE_MIME).split(':')
                          if (!swappable || fromId !== job.id || fromSide === side) return
                          e.preventDefault()
                          e.stopPropagation()
                          swapSides(job.id)
                        }}
                      >
                        <img src={src} alt="" draggable={false} className="h-14 w-10 rounded object-cover" />
                        <span className="absolute inset-x-0 bottom-0 rounded-b bg-black/60 text-center text-[9px] text-white">
                          {side === 'front' ? 'Front' : 'Back'}
                        </span>
                      </div>
                    )
                  })}
                  {job.back && job.status === 'queued' && (
                    <button
                      type="button"
                      onClick={() => swapSides(job.id)}
                      className="rounded p-1 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                      aria-label="Swap front and back"
                      title="Swap front and back"
                    >
                      <ArrowLeftRight size={14} />
                    </button>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-slate-700 dark:text-neutral-200">{job.front.name}</p>
                  {job.back && (
                    <p className="truncate text-xs text-slate-400">Back: {job.back.name}</p>
                  )}
                  <p className={`text-xs ${job.status === 'error' ? 'text-rose-600 dark:text-rose-400' : 'text-slate-400'}`}>
                    {job.status === 'queued' && 'Queued'}
                    {job.status === 'uploading' && 'Reading the card.'}
                    {job.status === 'error' && (job.message || 'Upload failed')}
                  </p>
                </div>
                {job.status !== 'uploading' && (
                  <button
                    type="button"
                    onClick={() => removeQueued(job)}
                    className="rounded p-1.5 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400"
                    aria-label={`Remove ${job.front.name}`}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
                {job.status === 'uploading' && <Loader2 size={16} className="animate-spin text-slate-400" />}
              </div>
            ))}
          </div>
        )}
      </section>

      {notice && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200">
          {notice}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 rounded-xl bg-white p-6 text-sm text-slate-400 dark:bg-neutral-800">
          <Loader2 size={16} className="animate-spin" /> Loading the scan queue.
        </div>
      ) : (
        <>
          {pending.length > 0 && (
            <section className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={addAllPending}
                    disabled={bulkAction !== null}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
                  >
                    {bulkAction === 'adding' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                    Add all ({pending.length})
                  </button>
                  {removeAllArmed ? (
                    <button
                      type="button"
                      onClick={removeAllPending}
                      disabled={bulkAction !== null}
                      className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-40"
                    >
                      {bulkAction === 'removing' && <Loader2 size={14} className="animate-spin" />}
                      Remove {pending.length} - confirm
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setRemoveAllArmed(true)}
                      disabled={bulkAction !== null}
                      className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:text-rose-600 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-200 dark:hover:text-rose-400"
                    >
                      <Trash2 size={14} />
                      Remove all
                    </button>
                  )}
                </div>
              </div>
              {pending.map((item) => (
                <ImportCard
                  key={item.id}
                  item={item}
                  condition={condition}
                  finishSeed={finish}
                  location={location}
                  sku={sku}
                  confirming={confirm.isPending && confirm.variables?.id === item.id}
                  dismissing={dismiss.isPending && dismiss.variables === item.id}
                  rescanning={rescan.isPending && rescan.variables === item.id}
                  onConfirm={(body, priceQuery) => confirm.mutate({ id: item.id, body, auto: false, priceQuery })}
                  onDismiss={() => dismiss.mutate(item.id)}
                  onRescan={() => rescan.mutate(item.id)}
                />
              ))}
            </section>
          )}

          {recent.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100">Added automatically</h2>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {recent.map((item) => (
                  <div key={item.id} className="flex items-center gap-3 rounded-xl bg-white p-3 dark:bg-neutral-800">
                    {item.image_url && (
                      <img src={item.image_url} alt="" className="h-14 w-10 rounded object-cover" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-800 dark:text-neutral-100">
                        {item.chosen_card_query || candidateName(item)}
                      </p>
                      <p className="truncate text-xs text-slate-400">
                        {item.chosen_card_query || 'Added to Inventory'}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => undo.mutate(item.id)}
                      disabled={undo.isPending && undo.variables === item.id}
                      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40 dark:text-neutral-400 dark:hover:bg-neutral-700 dark:hover:text-neutral-100"
                    >
                      {undo.isPending && undo.variables === item.id
                        ? <Loader2 size={12} className="animate-spin" />
                        : <Undo2 size={12} />}
                      Undo
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {pending.length === 0 && recent.length === 0 && data?.imports_enabled && (
            <div className="rounded-xl bg-white p-8 text-center dark:bg-neutral-800">
              <ScanLine size={28} className="mx-auto text-slate-300 dark:text-neutral-600" />
              <p className="mt-2 text-sm text-slate-500 dark:text-neutral-400">
                No scanned cards waiting. Take a photo to start.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// Enlarges the area under the pointer, the way a listing's photo zoom does: the
// image stays in its frame, the point being examined stays under the cursor.
function ZoomPhoto({ src }: { src: string }) {
  const [zoom, setZoom] = useState(false)
  const [origin, setOrigin] = useState('50% 50%')

  function point(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    return `${((e.clientX - rect.left) / rect.width) * 100}% ${((e.clientY - rect.top) / rect.height) * 100}%`
  }

  return (
    <div
      className="relative overflow-hidden rounded-lg cursor-zoom-in"
      onMouseEnter={(e) => { setOrigin(point(e)); setZoom(true) }}
      onMouseLeave={() => setZoom(false)}
      onMouseMove={(e) => setOrigin(point(e))}
    >
      <img
        src={src}
        alt=""
        className="h-48 w-36 object-cover transition-transform duration-200 ease-out sm:h-auto sm:w-full"
        style={{ transform: zoom ? 'scale(2.25)' : 'scale(1)', transformOrigin: origin }}
      />
    </div>
  )
}

function ImportCard({
  item, condition, finishSeed, location, sku, confirming, dismissing, rescanning, onConfirm, onDismiss, onRescan,
}: {
  item: InventoryImport
  condition: string
  finishSeed: CardFinish
  location: string
  sku: string
  confirming: boolean
  dismissing: boolean
  rescanning: boolean
  onConfirm: (body: Record<string, unknown>, priceQuery?: string) => void
  onDismiss: () => void
  onRescan: () => void
}) {
  const [chosen, setChosen] = useState<ImportCandidate | null>(item.candidates[0] ?? null)
  const [manual, setManual] = useState<ImportCandidate | null>(null)
  const [finish, setFinish] = useState<CardFinish>(finishSeed)
  const [cardCondition, setCardCondition] = useState(condition)
  const [quantity, setQuantity] = useState(1)
  const [cardLocation, setCardLocation] = useState(location)
  const [cardSku, setCardSku] = useState(sku)

  // A rescan replaces the recognizer's shortlist; keep the per-card condition,
  // quantity and notes, but start again from the new top candidate.
  const seenUpdate = useRef(item.updated_at)
  useEffect(() => {
    if (item.updated_at === seenUpdate.current) return
    seenUpdate.current = item.updated_at
    setManual(null)
    setChosen(item.candidates[0] ?? null)
    setFinish(finishSeed)
  }, [item.updated_at, item.candidates, finishSeed])

  const applied = chosen ? applyFinish({ card_query: chosen.card_query, name: chosen.name }, finish) : null
  const finishOptions: CardFinish[] = ['regular', ...finishesFor(chosen?.set_name)]
  const valid = Boolean(applied?.name.trim()) && quantity > 0
  // Keep the selected printing at the far left, including one picked from the
  // search that the recognizer did not return.
  const all = manual && !item.candidates.some((c) => c.card_query === manual.card_query)
    ? [manual, ...item.candidates]
    : item.candidates
  const selected = chosen ? all.find((c) => c.card_query === chosen.card_query) : undefined
  const candidates = selected
    ? [selected, ...all.filter((c) => c.card_query !== selected.card_query)]
    : all

  function pickCandidate(candidate: ImportCandidate, nextFinish: CardFinish = 'regular') {
    setChosen(candidate)
    setFinish(nextFinish)
  }

  function pickHit(hit: CardHit, nextFinish: CardFinish) {
    const picked: ImportCandidate = {
      card_query: hit.card_query,
      name: hit.name,
      set_name: hit.set_name,
      number: hit.number,
      rarity: hit.rarity,
      image_url: hit.image_url,
      score: 1,
      name_score: 1,
      number_match: true,
      visual_score: null,
    }
    setManual(picked)
    setChosen(picked)
    setFinish(nextFinish)
  }

  function pickFreeText(text: string, asSearch: boolean) {
    setManual(null)
    setChosen({
      card_query: asSearch ? text : '',
      name: text || item.detected_name || 'Scanned card',
      set_name: '',
      number: '',
      rarity: '',
      image_url: null,
      score: 0,
      name_score: 0,
      number_match: false,
      visual_score: null,
    })
    setFinish('regular')
  }

  function confirmCard() {
    if (!applied || !valid) return
    onConfirm({
      card_query: applied.card_query || null,
      name: applied.name.trim(),
      condition: cardCondition || null,
      quantity,
      location: cardLocation.trim() || null,
      sku: cardSku.trim() || null,
      auto: false,
    }, applied.card_query || undefined)
  }

  return (
    <div className="rounded-xl bg-white p-4 dark:bg-neutral-800">
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="flex shrink-0 gap-3 sm:w-64 sm:flex-col">
          {item.image_url ? (
            <ZoomPhoto src={item.image_url} />
          ) : (
            <div className="h-48 w-36 rounded-lg bg-slate-100 sm:h-80 sm:w-full dark:bg-neutral-700" />
          )}
          {item.back_image_url && <ZoomPhoto src={item.back_image_url} />}
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${confidenceTone(item.confidence)}`}>
                {item.confidence} confidence
              </span>
              <button
                type="button"
                onClick={onRescan}
                disabled={rescanning || confirming || dismissing}
                title="Run recognition again on the stored photo"
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40 dark:text-neutral-400 dark:hover:bg-neutral-700 dark:hover:text-neutral-100"
              >
                {rescanning ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                {rescanning ? 'Rescanning' : 'Rescan'}
              </button>
            </div>
            {item.score != null && (
              <p className="text-xs text-slate-400">{Math.round(item.score * 100)}% match score</p>
            )}
            {item.detected_name && (
              <p className="text-xs text-slate-500 dark:text-neutral-400">
                Read: {item.detected_name}{item.detected_number ? ` #${item.detected_number}` : ''}
              </p>
            )}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          {item.error && (
            <p className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
              {item.error}
            </p>
          )}

          {candidates.length > 0 ? (
            <div className="space-y-1">
              <div className="flex flex-wrap gap-2">
                {candidates.map((candidate) => {
                  const selected = chosen?.card_query === candidate.card_query
                  return (
                    <div
                      key={candidate.card_query}
                      className={`relative flex w-44 flex-col gap-1.5 rounded-lg border p-2 ${
                        selected
                          ? 'border-blue-300 bg-blue-50 dark:border-blue-500/40 dark:bg-blue-500/10'
                          : 'border-slate-200 dark:border-neutral-700'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => pickCandidate(candidate)}
                        className="block w-full text-left"
                      >
                        <CardArt artUrl={candidate.image_url} className="w-full rounded" fallback="back" />
                      </button>
                      <button
                        type="button"
                        onClick={() => pickCandidate(candidate)}
                        className="min-w-0 text-left"
                      >
                        <span className="block truncate text-sm text-slate-900 dark:text-neutral-100">
                          {candidate.name} <span className="text-slate-400">#{candidate.number}</span>
                        </span>
                        <span className="block truncate text-xs text-slate-500 dark:text-neutral-400">
                          {candidate.set_name}{candidate.rarity ? ` - ${candidate.rarity}` : ''}
                        </span>
                      </button>
                      <CardFinishButtons setName={candidate.set_name} onPick={(next) => pickCandidate(candidate, next)} />
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500 dark:text-neutral-400">
              No catalog match. Search for it, or add it as typed and price it yourself.
            </p>
          )}

          <div className="mt-3">
            <CardSearch
              onPick={pickHit}
              onSearchTerm={(text) => pickFreeText(text, true)}
              onFreeText={(text) => pickFreeText(text, false)}
              autoFocus={false}
              placeholder="Name, set, or number"
            />
          </div>


          <div className="mt-4 grid gap-3 border-t border-slate-100 pt-4 dark:border-neutral-700 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <label className="block">
              <span className="text-xs font-medium text-slate-500 dark:text-neutral-400">Condition</span>
              <select
                className={`${FIELD} mt-1 block w-full`}
                value={cardCondition}
                onChange={(e) => setCardCondition(e.target.value)}
              >
                <option value="">-</option>
                {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-500 dark:text-neutral-400">Finish</span>
              <select
                className={`${FIELD} mt-1 block w-full`}
                value={finish}
                onChange={(e) => setFinish(e.target.value as CardFinish)}
                disabled={!chosen?.card_query}
              >
                {finishOptions.map((f) => <option key={f} value={f}>{finishLabel(f)}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-500 dark:text-neutral-400">Quantity</span>
              <input
                type="number"
                min={1}
                step={1}
                className={`${FIELD} mt-1 block w-full tabular-nums`}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-500 dark:text-neutral-400">Location</span>
              <input
                value={cardLocation}
                onChange={(e) => setCardLocation(e.target.value)}
                maxLength={120}
                placeholder="Optional"
                className={`${FIELD} mt-1 block w-full`}
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-slate-500 dark:text-neutral-400">Lot</span>
              <input
                value={cardSku}
                onChange={(e) => setCardSku(e.target.value)}
                list="scan-lots"
                maxLength={40}
                placeholder="Optional"
                className={`${FIELD} mt-1 block w-full`}
              />
            </label>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={confirmCard}
              disabled={!valid || confirming || dismissing || rescanning}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              {confirming ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Add to Inventory
            </button>
            <button
              type="button"
              onClick={onDismiss}
              disabled={confirming || dismissing || rescanning}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:text-rose-600 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-200 dark:hover:text-rose-400"
            >
              {dismissing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              Remove
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}