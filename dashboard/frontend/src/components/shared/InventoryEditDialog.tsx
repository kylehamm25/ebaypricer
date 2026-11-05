import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { apiPut } from '../../lib/api'
import { PhotoUploader } from './PhotoUploader'
import { CardSearch } from './CardSearch'
import { applyFinish } from '../../lib/cardFinish'
import type { CardFinish } from '../../lib/cardFinish'
import { CONDITIONS } from '../../lib/conditions'
import type { CardHit, InventoryItem, LotOption } from '../../types'

const FIELD =
  'mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 ' +
  'dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm'

const LABEL = 'text-xs font-medium text-slate-600 dark:text-neutral-300'

// eBay's own ceiling on photos per item, mirrored from MAX_PHOTOS in
// routers/inventory.py, which is what actually enforces it.
const MAX_PHOTOS = 24

interface Form {
  name: string
  card_query: string | null
  set_name: string | null
  number: string | null
  condition: string
  quantity: string
  location: string
  sku: string
  cost: string
  manualValue: string
  photoUrls: string
  notes: string
}

function fromItem(item: InventoryItem): Form {
  return {
    name: item.name,
    card_query: item.card_query,
    set_name: item.set_name,
    number: item.number,
    condition: item.condition ?? '',
    quantity: String(item.quantity),
    location: item.location ?? '',
    sku: item.sku ?? '',
    cost: item.cost != null ? String(item.cost) : '',
    manualValue: item.manual_value != null ? String(item.manual_value) : '',
    photoUrls: item.photo_urls ?? '',
    notes: item.notes ?? '',
  }
}

// The shared search is the whole body of this step; only the heading and the
// way back to the details form belong to the dialog.
function SearchStep({ onPick, onSearchTerm, onFreeText, onBack }: {
  onPick: (hit: CardHit, finish: CardFinish) => void
  onSearchTerm: (text: string) => void
  onFreeText: (text: string) => void
  onBack: () => void
}) {
  return (
    <div className="flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-3">
        <button
          type="button"
          onClick={onBack}
          className="p-1 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200"
          aria-label="Back to details"
        >
          <ArrowLeft size={16} />
        </button>
        <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100">Which card?</h2>
      </div>

      <CardSearch
        onPick={onPick}
        onSearchTerm={onSearchTerm}
        onFreeText={onFreeText}
      />
    </div>
  )
}

export function InventoryEditDialog({ item, locations, skus, photoHostingEnabled, onClose }: {
  item: InventoryItem
  locations: string[]
  skus: LotOption[]
  photoHostingEnabled: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Form>(() => fromItem(item))
  const [step, setStep] = useState<'search' | 'details'>('details')

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))

  // Only for the hint under the field - the server is what normalises the list and
  // rejects a non-https link.
  const photoCount = form.photoUrls.split('|').filter((u) => u.trim()).length

  const qty = parseInt(form.quantity, 10)
  const valid = form.name.trim().length > 0 && Number.isFinite(qty) && qty > 0

  const save = useMutation({
    mutationFn: async () => {
      const cost = form.cost.trim()
      const body = {
        name: form.name.trim(),
        card_query: form.card_query,
        set_name: form.set_name,
        number: form.number,
        condition: form.condition.trim() || null,
        quantity: qty,
        location: form.location.trim() || null,
        sku: form.sku.trim() || null,
        // Blank clears it rather than saving 0 - "cost unknown" and "cost nothing"
        // are different facts, and most piles genuinely are the former.
        cost: cost === '' ? null : Number(cost),
        // Same blank-clears rule as cost, and it matters more here: clearing this
        // is how a row goes back to being priced from comps.
        manual_value: form.manualValue.trim() === '' ? null : Number(form.manualValue),
        // Sent as typed apart from the trim; the server normalises the pipe list and
        // refuses a non-https link, so no second copy of that rule lives here.
        photo_urls: form.photoUrls.trim() || null,
        notes: form.notes.trim() || null,
      }
      return apiPut(`/inventory/${item.id}`, body)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-5 w-full max-w-md max-h-[85vh] flex flex-col">
        {step === 'search' ? (
          <>
            <SearchStep
              onPick={(h, finish) => {
                const applied = applyFinish(h, finish)
                setForm((f) => ({
                  ...f,
                  card_query: applied.card_query,
                  set_name: h.set_name || null,
                  number: h.number || null,
                  // Only fill the name when it is still empty, so changing the card
                  // on an existing row never clobbers a description typed by hand.
                  // The finish suffix rides along with the catalog name, not a
                  // hand-typed one, for the same reason.
                  name: f.name.trim() || applied.name,
                }))
                setStep('details')
              }}
              onSearchTerm={(text) => {
                // The search words ARE the card_query. No set or number, which is
                // how the row reads back as a search rather than a catalog card.
                setForm((f) => ({
                  ...f,
                  card_query: text,
                  set_name: null,
                  number: null,
                  name: f.name.trim() || text,
                }))
                setStep('details')
              }}
              onFreeText={(text) => {
                setForm((f) => ({
                  ...f,
                  card_query: null,
                  set_name: null,
                  number: null,
                  name: f.name.trim() || text,
                }))
                setStep('details')
              }}
              onBack={() => setStep('details')}
            />
            <div className="flex justify-end pt-4">
              <button
                className="px-3 py-1.5 text-sm border border-slate-300 dark:border-neutral-600 rounded-lg text-slate-700 dark:text-neutral-200"
                onClick={onClose}
              >
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-lg font-bold text-slate-900 dark:text-neutral-100 mb-3">
              Edit item
            </h2>

            {/* What was chosen in step one, and the way back to change it. Shown in
                edit mode too, where it is the only route to the card search. */}
            <div className="flex items-center gap-2 rounded-lg bg-slate-100 dark:bg-neutral-700/60 px-3 py-2 mb-3">
              {/* A card_query with no set or number is a free-text eBay search, not
                  a catalog identity - labelled so, because the two are priced from
                  very different things. */}
              <span className="text-sm text-slate-900 dark:text-neutral-100 truncate">
                {form.card_query
                  ? (!form.set_name && !form.number
                      ? <><span className="text-slate-500 dark:text-neutral-400">eBay search: </span>{form.card_query}</>
                      : form.card_query)
                  : <span className="text-slate-500 dark:text-neutral-400">No card — priced by hand</span>}
              </span>
              <button
                type="button"
                onClick={() => setStep('search')}
                className="ml-auto shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline"
              >
                Change
              </button>
            </div>

            <div className="space-y-3 overflow-y-auto min-h-0">
              <label className="block">
                <span className={LABEL}>Name</span>
                <input
                  type="text"
                  autoFocus
                  maxLength={200}
                  className={FIELD}
                  value={form.name}
                  placeholder="What it is, e.g. Charizard ex 054 or Sealed ETB"
                  onChange={(e) => set('name', e.target.value)}
                />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className={LABEL}>Condition</span>
                  <select
                    className={FIELD}
                    value={form.condition}
                    onChange={(e) => set('condition', e.target.value)}
                  >
                    <option value="">—</option>
                    {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>

                <label className="block">
                  <span className={LABEL}>Quantity</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    className={`${FIELD} tabular-nums`}
                    value={form.quantity}
                    onChange={(e) => set('quantity', e.target.value)}
                  />
                </label>
              </div>

              <label className="block">
                <span className={LABEL}>Location</span>
                <input
                  type="text"
                  maxLength={120}
                  list="inventory-edit-locations"
                  className={FIELD}
                  value={form.location}
                  placeholder="Where it is, e.g. Box 3 / Binder A p.12"
                  onChange={(e) => set('location', e.target.value)}
                />
                {/* Existing values offered, not enforced - a new shelf should not
                    need a settings screen before anything can be put on it. */}
                <datalist id="inventory-edit-locations">
                  {locations.map((l) => <option key={l} value={l} />)}
                </datalist>
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className={LABEL}>Lot SKU</span>
                  <input
                    type="text"
                    maxLength={40}
                    list="inventory-edit-skus"
                    className={FIELD}
                    value={form.sku}
                    placeholder="L0042"
                    onChange={(e) => set('sku', e.target.value)}
                  />
                  <datalist id="inventory-edit-skus">
                    {skus.map((l) => <option key={l.sku} value={l.sku}>{l.title || undefined}</option>)}
                  </datalist>
                </label>

                <label className="block">
                  <span className={LABEL}>Cost each</span>
                  <div className="relative mt-1">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      className="w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg pl-7 pr-3 py-1.5 text-sm tabular-nums"
                      value={form.cost}
                      placeholder="Optional"
                      onChange={(e) => set('cost', e.target.value)}
                    />
                  </div>
                </label>
              </div>

              <label className="block">
                <span className={LABEL}>Your price (each)</span>
                <div className="relative mt-1">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className="w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 rounded-lg pl-7 pr-3 py-1.5 text-sm tabular-nums"
                    value={form.manualValue}
                    placeholder={form.card_query ? 'Overrides the comp price' : 'What it is worth'}
                    onChange={(e) => set('manualValue', e.target.value)}
                  />
                </div>
                <span className="block text-xs text-slate-400 mt-1">
                  {form.card_query
                    ? 'Used instead of the comp average. Condition is not applied to it.'
                    : 'Sealed, bulk and anything already appraised. Condition is not applied to it.'}
                </span>
              </label>

              {/* Web-hosted links, in the order they should appear on the listing -
                  eBay reads the FIRST one to work out what the item is. This is the
                  only place photos are stored: the card art shown elsewhere is
                  catalog art of the printing, not a photo of this card, and it can't
                  show a condition. */}
              <PhotoUploader
                itemId={item.id}
                urls={form.photoUrls}
                onChange={(urls) => set('photoUrls', urls)}
                enabled={photoHostingEnabled}
              />

              {/* Still here under the uploader, for a photo already hosted somewhere
                  else - an eBay Picture Services URL, or an existing listing's image.
                  Uploading writes through this same field, so the two never disagree. */}
              <label className="block">
                <span className={LABEL}>Photo URLs</span>
                <textarea
                  rows={2}
                  className={`${FIELD} resize-none font-mono text-xs`}
                  value={form.photoUrls}
                  placeholder="https://... | https://..."
                  onChange={(e) => set('photoUrls', e.target.value)}
                />
                <span className="block text-xs text-slate-400 mt-1">
                  {photoCount > 0
                    ? `${photoCount} ${photoCount === 1 ? 'photo' : 'photos'}, first one first`
                    : `Up to ${MAX_PHOTOS}, separated by |. Must be https and end in .jpg or .png.`}
                </span>
              </label>

              <label className="block">
                <span className={LABEL}>Notes</span>
                <textarea
                  rows={2}
                  className={`${FIELD} resize-none`}
                  value={form.notes}
                  onChange={(e) => set('notes', e.target.value)}
                />
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
                disabled={save.isPending || !valid}
              >
                {save.isPending && <Loader2 size={14} className="animate-spin" />}
                Save
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
