const BASE = 'http://127.0.0.1:8000/api/v1'

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.statusText}`)
  return res.json()
}

export async function apiText(path: string): Promise<string> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.statusText}`)
  return res.text()
}

export async function apiPost(path: string): Promise<unknown> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST' })
  if (!res.ok) throw new Error(`API error: ${res.statusText}`)
  return res.json()
}
