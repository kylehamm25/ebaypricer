import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { ImagePlus, Loader2, Star, X } from 'lucide-react'
import { apiPost } from '../../lib/api'
import { sortByName, uploadPhotos } from '../../lib/photos'

// eBay's ceiling per item, mirrored from MAX_PHOTOS in routers/inventory.py, which is
// what actually enforces it.
const MAX_PHOTOS = 24

/** Photos of the actual card, hosted where eBay can fetch them.
 *
 *  Uploads write to the row immediately rather than waiting for Save, because the file
 *  has already left the browser by then and a cancelled dialog would orphan it in the
 *  bucket. The parent's form state is kept in step through `onChange`, so pressing
 *  Save afterwards can't put a stale list back over what was uploaded.
 *
 *  Order is meaningful: eBay uses the FIRST photo as the listing's main image, and its
 *  prefill flow reads that one to work out what the item is. A multi-select is sorted
 *  by filename on the way in because the browser cannot tell us the order they were
 *  clicked, and the Main badge is the manual correction when that guess is wrong.
 *  Nothing sorts the stored list after that. */
export function PhotoUploader({ itemId, urls, onChange, enabled }: {
  itemId: number
  /** Pipe-separated, as the row stores it. */
  urls: string
  onChange: (urls: string) => void
  /** False when the server has no Supabase credentials - the control explains itself
   *  rather than offering a button that fails on every file. */
  enabled: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  // Counts nested enter/leave pairs rather than toggling on each one: the browser
  // fires dragleave for every child boundary crossed on the way to the drop
  // target, and a plain boolean would flicker the highlight off mid-drag.
  const dragDepth = useRef(0)

  const list = urls.split('|').map((u) => u.trim()).filter(Boolean)

  const run = async (fn: () => Promise<string[]>) => {
    setBusy(true)
    setError(null)
    try {
      onChange((await fn()).join('|'))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const remove = (url: string) =>
    run(async () => {
      const res = await apiPost(`/inventory/${itemId}/photos/remove`, { url }) as { photo_urls: string[] }
      return res.photo_urls
    })

  /** Promote one photo to the front. Written through the server rather than held in
   *  form state, because uploads already write immediately - a reorder that only
   *  lived until Save could be lost while the photos it reordered were not. */
  const makeMain = (url: string) =>
    run(async () => {
      const res = await apiPost(`/inventory/${itemId}/photos/reorder`, {
        urls: [url, ...list.filter((u) => u !== url)],
      }) as { photo_urls: string[] }
      return res.photo_urls
    })

  // Dragover must be prevented too, not just drop - without it the browser never
  // treats the element as a valid drop target and drop never fires at all.
  const onDragEnter = (e: DragEvent) => {
    e.preventDefault()
    if (!enabled || busy) return
    dragDepth.current += 1
    setDragging(true)
  }
  const onDragOver = (e: DragEvent) => e.preventDefault()
  const onDragLeave = (e: DragEvent) => {
    e.preventDefault()
    if (!enabled || busy) return
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    if (!enabled || busy) return
    // No type filter, same as the file picker below: an extension guess has
    // already been seen to hide good files, and the server decides by decoding
    // the bytes rather than trusting what the browser or OS claims a file is.
    const files = sortByName([...e.dataTransfer.files])
    if (files.length) run(() => uploadPhotos(itemId, files))
  }

  return (
    <div
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-600 dark:text-neutral-300">Photos</span>
        <span className="text-xs text-slate-400">
          {list.length > 0
            ? `${list.length} of ${MAX_PHOTOS} — first is the main image`
            : enabled ? 'eBay needs at least one — drag files in or click to add' : 'eBay needs at least one'}
        </span>
      </div>

      <div
        className={`mt-2 flex flex-wrap gap-2 rounded-lg transition-colors ${
          dragging ? 'ring-2 ring-blue-500/60 bg-blue-50/50 dark:bg-blue-500/10' : ''
        }`}
      >
        {list.map((url, i) => (
          <div key={url} className="relative group">
            <img
              src={url}
              alt={i === 0 ? 'Main photo' : `Photo ${i + 1}`}
              className="w-16 h-20 object-cover rounded border border-slate-200 dark:border-neutral-600 bg-slate-50 dark:bg-neutral-900"
            />
            {/* Said out loud, because which photo is first is not a cosmetic
                detail - it is the one eBay reads to identify the card. */}
            {i === 0 ? (
              <span className="absolute bottom-0 inset-x-0 bg-black/60 text-white text-[10px] text-center rounded-b">
                Main
              </span>
            ) : (
              // Windows hands a multi-select back in folder order, not the order you
              // clicked, so the sort below is a good guess and this is the correction.
              <button
                type="button"
                onClick={() => makeMain(url)}
                disabled={busy}
                title="Use as the main photo"
                aria-label={`Use photo ${i + 1} as the main photo`}
                className="absolute bottom-0 inset-x-0 bg-black/60 text-white text-[10px] rounded-b py-0.5 opacity-0 group-hover:opacity-100 focus:opacity-100 disabled:opacity-40 inline-flex items-center justify-center gap-0.5"
              >
                <Star size={9} /> Main
              </button>
            )}
            <button
              type="button"
              onClick={() => remove(url)}
              disabled={busy}
              aria-label={`Remove photo ${i + 1}`}
              className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-slate-700 text-white grid place-items-center opacity-0 group-hover:opacity-100 focus:opacity-100 disabled:opacity-40"
            >
              <X size={11} />
            </button>
          </div>
        ))}

        {enabled && list.length < MAX_PHOTOS && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="w-16 h-20 rounded border border-dashed border-slate-300 dark:border-neutral-600 grid place-items-center text-slate-400 hover:text-slate-600 dark:hover:text-neutral-300 disabled:opacity-40"
            title="Add photos, or drag and drop them anywhere in this box"
            aria-label="Add photos"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <ImagePlus size={16} />}
          </button>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        // No `accept`: an extension filter on Windows has already been seen to hide
        // perfectly good files, and the server settles what a file is by decoding it
        // rather than by trusting a type header the browser guessed.
        className="hidden"
        onChange={(e) => {
          const files = sortByName([...(e.target.files ?? [])])
          // Cleared so picking the same file again still fires a change event, which
          // is how you retry after a rejected upload.
          e.target.value = ''
          if (files.length) run(() => uploadPhotos(itemId, files))
        }}
      />

      {!enabled && (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
          Photo hosting is off — set SUPABASE_URL and SUPABASE_SERVICE_KEY to upload
          here, or paste hosted links below.
        </p>
      )}

      {error && <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">{error}</p>}
    </div>
  )
}
