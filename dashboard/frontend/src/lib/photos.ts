import { supabase } from './supabase'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

/** Multipart, so it can't go through `lib/api.ts` - that helper JSON-encodes its
 *  body and sets Content-Type, and multipart needs the browser to set its own
 *  boundary. Shared by `PhotoUploader` and any drop target that uploads straight
 *  to a row without opening it, so there is exactly one copy of this request. */
export async function uploadPhotos(itemId: number, files: File[]): Promise<string[]> {
  const body = new FormData()
  for (const f of files) body.append('files', f)
  const { data } = await supabase.auth.getSession()
  const res = await fetch(`${BASE}/inventory/${itemId}/photos`, {
    method: 'POST',
    headers: data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {},
    body,
  })
  const json = await res.json().catch(() => null)
  if (!res.ok) {
    throw new Error(typeof json?.detail === 'string' ? json.detail : `Upload failed: ${res.statusText}`)
  }
  return json.photo_urls as string[]
}

/** Numeric-aware filename sort, shared by every file picker and drop target: a
 *  Windows multi-select and a drag out of a folder both hand files back in
 *  display order rather than the order they were picked, and camera filenames
 *  run in shot order (IMG_0775 before IMG_0776), so this is the closest thing to
 *  intent either source gives us. The Main badge in `PhotoUploader` is the manual
 *  correction when the guess is wrong. */
export function sortByName(files: File[]): File[] {
  return [...files].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }),
  )
}
