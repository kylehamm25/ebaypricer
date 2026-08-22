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

/** Tailwind text colour for a profit/loss figure: green above zero, red below,
 *  muted when there is no figure at all. Shared so every page colours money the
 *  same way. */
export function profitTone(v: number | null | undefined): string {
  if (v == null) return 'text-slate-400'
  if (v > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (v < 0) return 'text-rose-600 dark:text-rose-400'
  return 'text-slate-500 dark:text-neutral-400'
}

/** Parses a possibly-formatted numeric field (e.g. a currency string with stray
 *  characters) from an API row into a plain number, or null if it isn't one. */
export function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(String(v).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(n) ? n : null
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
  ese_max_price: 'capped to stay under the eBay Standard Envelope $20 limit',
}

/** Human-readable explanation of a stored suggestion, for a tooltip. Presentation
 *  only - it reformats what the backend already decided, it never recomputes. */
export function formatSuggestionReason(basis: SuggestedPriceBasis | null | undefined): string {
  if (!basis) return 'No suggestion available.'
  if (basis.status === 'cooldown') {
    const cooldown = basis.cooldown_days ?? 5
    const since = basis.days_since_price_change
    const remaining = since != null ? Math.max(1, Math.ceil(cooldown - since)) : cooldown
    return `Repriced ${since != null ? `${Math.floor(since)}d ago` : 'recently'} — no new suggestion for another ${remaining}d, to give the new price time to work.`
  }
  if (basis.status === 'comp_mismatch') {
    const avg = basis.anchor_avg
    const ratio = basis.anchor_ratio
    const dir = ratio != null && ratio > 1 ? 'higher' : 'lower'
    const times = ratio != null ? (ratio > 1 ? ratio : 1 / ratio).toFixed(1) : '?'
    return `No suggestion — the competitor listings found for this card average ${
      avg != null ? formatCurrency(avg) : 'far off'}, about ${times}× ${dir} than this listing's price.`
      + ` That gap means the comps are almost certainly a different product (damage, a novelty print, a promo stamp), so they say nothing about what this is worth.`
  }
  if (basis.status === 'thin_comps') return `Too few competitor listings (${basis.comps ?? 0}) to suggest a price.`
  if (basis.status === 'no_comps') return 'No competitor listings found for this card.'
  if (basis.status === 'excluded') {
    return `No suggestion for print-defect/novelty variants${basis.matched_keyword ? ` (matched "${basis.matched_keyword}")` : ''}.`
  }

  const parts: string[] = []
  if (basis.days_listed != null) parts.push(`listed ${basis.days_listed}d`)
  if (basis.rank != null) parts.push(`rank #${basis.rank}`)
  if (basis.anchor_floor != null && basis.anchor_avg != null) {
    parts.push(`comps ${formatCurrency(basis.anchor_floor)}–${formatCurrency(basis.anchor_avg)} (${basis.comps ?? 0})`)
  }
  if (basis.condition && basis.condition_mult != null && basis.condition_mult !== 1) {
    parts.push(`${basis.condition} ×${basis.condition_mult}`)
  }
  if (basis.shipping_adjustment && Math.abs(basis.shipping_adjustment) >= 0.01) {
    const dir = basis.shipping_adjustment > 0 ? 'up' : 'down'
    parts.push(`shipping-adjusted ${dir} ${formatCurrency(Math.abs(basis.shipping_adjustment))} vs comps' total price`)
  }
  if (basis.watchers && basis.watcher_pull) {
    parts.push(`${basis.watchers} watchers holding price closer to current`)
  }
  for (const c of basis.clamps ?? []) {
    parts.push(CLAMP_LABELS[c] ?? c)
  }
  if (basis.flags?.includes('low_confidence')) parts.push('low confidence')
  return parts.join(' · ')
}
