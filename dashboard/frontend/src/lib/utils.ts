import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(n: number | string | null | undefined): string {
  const v = typeof n === 'string' ? parseFloat(n) : n
  if (v == null || isNaN(v)) return '—'
  return '$' + v.toFixed(2)
}

export function formatPercent(n: number | string | null | undefined): string {
  const v = typeof n === 'string' ? parseFloat(n) : n
  if (v == null || isNaN(v)) return '—'
  return (v * 100).toFixed(1) + '%'
}

export function formatInt(n: number | string | null | undefined): string {
  const v = typeof n === 'string' ? parseInt(n) : n
  if (v == null || isNaN(v)) return '—'
  return v.toLocaleString()
}
