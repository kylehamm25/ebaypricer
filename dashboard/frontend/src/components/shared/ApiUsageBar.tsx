import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { RateLimitsResponse } from '../../types'

// Matches the server-side cache TTL in routers/ebay.py - polling faster only re-serves
// the same cached reading, and reading the quota is itself a metered eBay call.
const REFETCH_MS = 5 * 60 * 1000

// Browse is the API this app can actually exhaust (one call per card per day, and the
// valuation page lets a person spend them by typing), so headroom matters well before
// the quota is gone.
const WARN_PCT = 70
const DANGER_PCT = 90

function barColor(pct: number): string {
  if (pct >= DANGER_PCT) return 'bg-red-500'
  if (pct >= WARN_PCT) return 'bg-amber-500'
  return 'bg-emerald-500'
}

export function ApiUsageBar() {
  const { data } = useQuery<RateLimitsResponse>({
    queryKey: ['ebay-rate-limits'],
    queryFn: () => api('/ebay/rate-limits'),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS,
  })

  const limits = data?.limits ?? []
  const reset = limits.find((l) => l.reset)?.reset

  return (
    <div className="p-6 bg-white dark:bg-neutral-800 rounded-lg">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-neutral-100">eBay API Usage</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-neutral-400">
        Share of today's quota used, read from eBay rather than estimated.
        {reset && ` Resets ${new Date(reset).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`}
      </p>

      {/* The endpoint returns an empty list when eBay is unreachable or the app lacks
          access. Say so rather than drawing empty bars, which would read as "no usage"
          instead of "no data". */}
      {!limits.length ? (
        <p className="mt-4 text-sm text-slate-400 dark:text-neutral-500">
          Usage data unavailable.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {limits.map((l) => (
            <div key={l.name}>
              <div className="flex items-baseline justify-between text-sm mb-1">
                <span className="text-slate-700 dark:text-neutral-200">{l.name}</span>
                <span className="tabular-nums text-slate-500 dark:text-neutral-400">{l.pct}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-100 dark:bg-neutral-700 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor(l.pct)}`}
                  // Always leave a sliver visible: a hairline still reads as "measured
                  // and low", where a zero-width bar looks like a broken widget.
                  style={{ width: `${Math.max(l.pct, 1.5)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
