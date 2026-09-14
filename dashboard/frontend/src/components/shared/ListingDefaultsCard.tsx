import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileUp, Loader2, Trash2 } from 'lucide-react'
import { api, apiDelete, apiPut } from '../../lib/api'
import { supabase } from '../../lib/supabase'
import type {
  ListingDefaults, ListingDefaultsResponse, ListingDefaultsSaveResponse,
  PrefillTemplateMeta, PrefillTemplateUpload,
} from '../../types'

const FIELD =
  'mt-1 w-full border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 ' +
  'dark:text-neutral-100 rounded-lg px-3 py-1.5 text-sm'

const LABEL = 'text-xs font-medium text-slate-600 dark:text-neutral-300'

// Shipping profiles SHIPPING_PRICE_MAP in ebaypricer/listing_economics.py knows the
// buyer-paid postage of. A name outside them is a real policy eBay will accept, but
// the CSV's price floor then assumes the buyer is charged nothing - so these are
// offered as a datalist and anything else is flagged rather than blocked.
//
// Spelled the way eBay's own business policies are, NOT the way the map's keys are.
// The lookup lowercases, so casing is free here and load-bearing there: eBay matches
// a policy by its exact name, and suggesting "eBay standard envelope" for a policy
// actually called "Ebay standard envelope" got a real upload rejected (21917327).
const PRICED_SHIPPING_PROFILES = [
  'Free ebay standard',
  'Ebay standard envelope',
  'Ground Advantage',
  'Free Ground',
]

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

/** Multipart, so it can't go through `apiPut` — that helper JSON-encodes its body and
 *  sets Content-Type, and multipart needs the browser to set its own boundary. The
 *  auth header is built the way `lib/api.ts` builds it. */
async function uploadTemplate(file: File): Promise<PrefillTemplateUpload> {
  const body = new FormData()
  body.append('file', file)
  const { data } = await supabase.auth.getSession()
  const res = await fetch(`${BASE}/settings/prefill-template`, {
    method: 'PUT',
    headers: data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {},
    body,
  })
  if (!res.ok) {
    const detail = await res.json().then((d) => d?.detail).catch(() => null)
    throw new Error(typeof detail === 'string' ? detail : `API error: ${res.statusText}`)
  }
  return res.json()
}

// The four the CSV endpoint actually refuses to run without - min_price is
// deliberately excluded, since it is optional and never gates the CSV.
const REQUIRED_FIELDS: (keyof ListingDefaults)[] =
  ['item_location', 'shipping_profile', 'payment_profile', 'return_profile']

const EMPTY: ListingDefaults = {
  item_location: '',
  shipping_profile: '',
  payment_profile: '',
  return_profile: '',
  min_price: null,
}

/** The standing settings behind the Inventory page's listing CSV.
 *
 *  Here rather than in that dialog because they are the same on every export
 *  forever, and here rather than in localStorage because they are account facts, not
 *  a browser convenience: an eBay business policy name that doesn't match Seller Hub
 *  exactly is the commonest reason a bulk upload comes back rejected, so it should
 *  hold on every machine you sign in from. */
export function ListingDefaultsCard() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<ListingDefaultsResponse>({
    queryKey: ['listing-defaults'],
    queryFn: () => api('/settings/listing-defaults'),
  })

  const [form, setForm] = useState<ListingDefaults>(EMPTY)
  const [dirty, setDirty] = useState(false)

  // Server values win until the first edit, so a refetch can't yank a half-typed
  // policy name out from under the cursor.
  useEffect(() => {
    if (data && !dirty) setForm(data.listing_defaults)
  }, [data, dirty])

  const set = (patch: Partial<ListingDefaults>) => {
    setDirty(true)
    setForm((f) => ({ ...f, ...patch }))
  }

  const save = useMutation({
    mutationFn: () =>
      apiPut('/settings/listing-defaults', form) as Promise<ListingDefaultsSaveResponse>,
    onSuccess: (res) => {
      setDirty(false)
      queryClient.setQueryData(['listing-defaults'], res)
      // The rows themselves live on a different page; invalidate rather than trying
      // to patch them in here, since this card has no idea which ones changed.
      if (res.raised_to_minimum > 0) queryClient.invalidateQueries({ queryKey: ['inventory'] })
    },
  })

  const unpricedProfile =
    !!form.shipping_profile.trim() &&
    !PRICED_SHIPPING_PROFILES.some(
      (p) => p.toLowerCase() === form.shipping_profile.trim().toLowerCase(),
    )

  const complete = REQUIRED_FIELDS.every((k) => (form[k] as string).trim())

  return (
    <div className="p-6 bg-white dark:bg-neutral-800 rounded-lg">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-neutral-100">Listing defaults</h2>

      {isLoading ? (
        <div className="mt-6 flex items-center gap-2 text-slate-400">
          <Loader2 size={18} className="animate-spin" /> Loading...
        </div>
      ) : data && !data.listing_defaults_enabled ? (
        <div className="mt-6 flex items-start gap-3 text-sm text-slate-600 dark:text-neutral-300">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
          <p>
            Run{' '}
            <code className="px-1 rounded bg-slate-100 dark:bg-neutral-700">
              db/migrations/0015_listing_defaults.sql
            </code>{' '}
            in the Supabase SQL editor, then reload.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className={LABEL}>Item location</span>
              <input
                type="text"
                maxLength={60}
                className={FIELD}
                value={form.item_location}
                placeholder="ZIP code"
                onChange={(e) => set({ item_location: e.target.value })}
              />
            </label>
            <label className="block">
              <span className={LABEL}>Shipping policy</span>
              <input
                type="text"
                maxLength={80}
                list="listing-defaults-shipping"
                className={FIELD}
                value={form.shipping_profile}
                placeholder="Free ebay standard"
                onChange={(e) => set({ shipping_profile: e.target.value })}
              />
              <datalist id="listing-defaults-shipping">
                {PRICED_SHIPPING_PROFILES.map((p) => <option key={p} value={p} />)}
              </datalist>
            </label>
            <label className="block">
              <span className={LABEL}>Payment policy</span>
              <input
                type="text"
                maxLength={80}
                className={FIELD}
                value={form.payment_profile}
                placeholder="Name in Seller Hub"
                onChange={(e) => set({ payment_profile: e.target.value })}
              />
            </label>
            <label className="block">
              <span className={LABEL}>Return policy</span>
              <input
                type="text"
                maxLength={80}
                className={FIELD}
                value={form.return_profile}
                placeholder="Name in Seller Hub"
                onChange={(e) => set({ return_profile: e.target.value })}
              />
            </label>
            <label
              className="block"
              title="Optional. The Listing CSV button won't open a listing below this price, even when comps and fees/postage alone would allow less."
            >
              <span className={LABEL}>Minimum listing price</span>
              <input
                type="number"
                min={0}
                step="0.01"
                className={FIELD}
                value={form.min_price ?? ''}
                placeholder="No minimum"
                onChange={(e) => {
                  const raw = e.target.value
                  set({ min_price: raw === '' ? null : Number(raw) })
                }}
              />
            </label>
          </div>

          {unpricedProfile && (
            <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">
              Postage for this profile isn't known, so CSV prices are floored as if
              shipping cost nothing.
            </p>
          )}

          <div className="mt-6 pt-5 border-t border-slate-100 dark:border-neutral-700">
            <h3 className="text-sm font-medium text-slate-900 dark:text-neutral-100">
              eBay prefill template
            </h3>
            <PrefillTemplateRow stored={data?.prefill_template ?? null} />
          </div>

          <div className="mt-5 flex items-center gap-3">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending || !dirty}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {save.isPending && <Loader2 size={16} className="animate-spin" />}
              Save
            </button>
            {!dirty && save.isSuccess && (
              <span className="inline-flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={16} />
                {save.data.raised_to_minimum > 0
                  ? `Saved — raised ${save.data.raised_to_minimum} inventory ${save.data.raised_to_minimum === 1 ? 'row' : 'rows'} to the minimum`
                  : 'Saved'}
              </span>
            )}
            {!complete && (
              <span className="text-xs text-slate-400">
                All four are needed before a CSV can be built.
              </span>
            )}
          </div>

          {save.isError && (
            <p className="mt-3 text-xs text-rose-600 dark:text-rose-400">
              {(save.error as Error).message}
            </p>
          )}
        </>
      )}
    </div>
  )
}


/** eBay's blank prefill template, kept on file so the Inventory page's export stops
 *  asking for it.
 *
 *  Stored rather than generated because eBay's instructions say not to change the
 *  file's formatting — the app can only fill in theirs. Checked here rather than at
 *  export time: a template rejected now costs one re-download, while one rejected
 *  mid-export wastes the selection that was about to go into it. */
function PrefillTemplateRow({ stored }: { stored: PrefillTemplateMeta | null }) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = useMutation({
    mutationFn: (file: File) => uploadTemplate(file),
    onSuccess: (res) => queryClient.setQueryData(['listing-defaults'], res),
  })
  const remove = useMutation({
    mutationFn: () => apiDelete('/settings/prefill-template'),
    onSuccess: (res) => queryClient.setQueryData(['listing-defaults'], res),
  })

  const found = upload.data

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        // No `accept`. It built a Windows explorer filter that listed nothing at all,
        // hiding a perfectly good .xlsx sitting in Downloads - and it was never the
        // gate: the server checks the suffix, the size, and then whether openpyxl can
        // actually read the file as eBay's template, which is a far better answer than
        // a picker that silently shows an empty folder.
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          // Cleared so choosing the same file twice still fires a change event, which
          // is how you retry after a rejected upload.
          e.target.value = ''
          if (f) upload.mutate(f)
        }}
      />

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
          className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 text-sm rounded-lg text-slate-700 dark:text-neutral-200 disabled:opacity-50"
        >
          {upload.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
          {stored ? 'Replace' : 'Upload template'}
        </button>

        {stored ? (
          <>
            <span className="text-sm text-slate-600 dark:text-neutral-300">{stored.name}</span>
            {stored.uploaded_at && (
              <span className="text-xs text-slate-400">
                {new Date(stored.uploaded_at).toLocaleDateString()}
              </span>
            )}
            <button
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="p-1.5 rounded-md text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 disabled:opacity-40"
              aria-label="Remove the stored template"
            >
              {remove.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          </>
        ) : (
          <span className="text-xs text-slate-400">
            Seller Hub → Reports → Autofill listing details. The .xlsx one.
          </span>
        )}
      </div>

      {/* Which file belongs here, said next to the control rather than in a heading.
          eBay hands out several bulk templates and only this one is stored: the
          draft-listing CSV is GENERATED by the Listing CSV button, so bringing it
          here gets a "must be .xlsx" rejection that explains the extension but not
          the mistake. */}
      <p className="mt-2 text-xs text-slate-400">
        Only for the Inventory page's Prefill template button. The Listing CSV button
        writes its own file and needs nothing here.
      </p>

      {/* Only after an upload: what the file actually turned out to contain. A
          template eBay has revised shows up here rather than after a round trip. */}
      {found && found.missing_columns.length > 0 && (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
          No {found.missing_columns.map((c) => c.replace(/_/g, ' ')).join(', ')} column
          in that template — that data will be left out.
        </p>
      )}

      {(upload.isError || remove.isError) && (
        <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
          {((upload.error ?? remove.error) as Error).message}
        </p>
      )}
    </>
  )
}
