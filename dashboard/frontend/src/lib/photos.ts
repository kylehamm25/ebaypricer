import { supabase } from './supabase'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

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

export function sortByName(files: File[]): File[] {
  return [...files].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }),
  )
}
