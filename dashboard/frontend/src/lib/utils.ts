import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { SuggestedPriceBasis } from '../types'

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

// NOTE: the suggested price is NOT computed here any more. It is computed once,
// server-side, in dashboard/backend/services/suggested_price.py and stored on the
// listing row - both pages just read `Suggested Price`. There used to be a
// computeRecommendedPrice() in this file called from two pages with different
// inputs, which produced two different "suggested" numbers for the same listing.
// Keep pricing logic out of the client so that cannot happen again.

const CLAMP_LABELS: Record<string, string> = {
  change_cap: 'limited by max change per step',
  net_floor: 'held at minimum profitable price',
  absolute_floor: 'held at minimum price',
}

/** Human-readable explanation of a stored suggestion, for a tooltip. Presentation
 *  only - it reformats what the backend already decided, it never recomputes. */
export function formatSuggestionReason(basis: SuggestedPriceBasis | null | undefined): string {
  if (!basis) return 'No suggestion available.'
  if (basis.status === 'thin_comps') return `Too few competitor listings (${basis.comps ?? 0}) to suggest a price.`
  if (basis.status === 'no_comps') return 'No competitor listings found for this card.'

  const parts: string[] = []
  if (basis.days_listed != null) parts.push(`listed ${basis.days_listed}d`)
  if (basis.rank != null) parts.push(`rank #${basis.rank}`)
  if (basis.anchor_floor != null && basis.anchor_avg != null) {
    parts.push(`comps ${formatCurrency(basis.anchor_floor)}–${formatCurrency(basis.anchor_avg)} (${basis.comps ?? 0})`)
  }
  if (basis.condition && basis.condition_mult != null && basis.condition_mult !== 1) {
    parts.push(`${basis.condition} ×${basis.condition_mult}`)
  }
  for (const c of basis.clamps ?? []) {
    parts.push(CLAMP_LABELS[c] ?? c)
  }
  if (basis.flags?.includes('low_confidence')) parts.push('low confidence')
  return parts.join(' · ')
}
