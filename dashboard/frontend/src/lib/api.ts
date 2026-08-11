import { supabase } from './supabase'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

async function headers(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const h: Record<string, string> = {}
  if (data.session) h.Authorization = `Bearer ${data.session.access_token}`
  return h
}

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: await headers() })
  if (!res.ok) throw new Error(`API error: ${res.statusText}`)
  return res.json()
}

export async function apiText(path: string): Promise<string> {
  const res = await fetch(`${BASE}${path}`, { headers: await headers() })
  if (!res.ok) throw new Error(`API error: ${res.statusText}`)
  return res.text()
}

export async function apiPost(path: string, body?: unknown): Promise<unknown> {
  const h = await headers()
  if (body !== undefined) h['Content-Type'] = 'application/json'
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: h,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().then((d) => d?.detail).catch(() => null)
    throw new Error(typeof detail === 'string' ? detail : `API error: ${res.statusText}`)
  }
  return res.json()
}
