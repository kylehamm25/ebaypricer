import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'
import {
  ArrowLeft,
  Check,
  Clock,
  ExternalLink,
  Loader2,
  PackageSearch,
  Pencil,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react'
import { api, apiPost } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { KpiCard } from '../components/shared/KpiCard'
import { CardMatchDialog } from '../components/shared/CardMatchDialog'
import { CardBack } from '../components/shared/ViewToggle'
import { KpiSkeleton, ChartSkeleton, TableSkeleton } from '../components/shared/Skeleton'
import { useChartCursor } from '../lib/theme'
import { cn, formatCurrency, formatInt, formatSuggestionReason, toNumber } from '../lib/utils'
import type {
  ActiveListing, CardPriceDetail, PositionHistoryPoint, PriceComparison, SuggestedPriceBasis,
} from '../types'

const chip = "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"

function formatShortDate(v: string | null | undefined) {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function renderListingLink(r: Record<string, unknown>) {
  return r.url ? (
    <a
      href={r.url as string}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 dark:text-blue-400 hover:underline inline-flex"
      title="View on eBay"
    >
      <ExternalLink size={13} />
    </a>
  ) : null
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-slate-400">
      <p className="text-sm">{label}</p>
    </div>
  )
}

interface PriceHistoryPoint {
  date: string
  active?: number
}

export function ListingDetailPage() {
  const cursor = useChartCursor()
  const { itemId } = useParams<{ itemId: string }>()
  const queryClient = useQueryClient()

  const { data: item, isLoading } = useQuery<ActiveListing | null>({
    queryKey: ['active-item', itemId],
    queryFn: () => api(`/active/item/${encodeURIComponent(itemId!)}`),
    enabled: !!itemId,
  })

  const [editingPrice, setEditingPrice] = useState(false)
  const [editingCard, setEditingCard] = useState(false)
  // Reset per listing, or navigating from a card with no art to one with art
  // would keep showing the back.
  const [artFailed, setArtFailed] = useState(false)
  useEffect(() => { setArtFailed(false) }, [itemId])
  const [priceInput, setPriceInput] = useState('')

  const revisePriceMutation = useMutation({
    mutationFn: (price: number) => apiPost(`/active/item/${encodeURIComponent(itemId!)}/price`, { price }),
    onSuccess: () => {
      setEditingPrice(false)
      queryClient.invalidateQueries({ queryKey: ['active-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['active-list'] })
      queryClient.invalidateQueries({ queryKey: ['active-summary'] })
      // The price just changed, so the comparison figures and the suggestion (which is
      // computed relative to the current price) are stale. Without these the page kept
      // showing pre-change numbers until the 120s background refetch.
      queryClient.invalidateQueries({ queryKey: ['pricing-comparisons'] })
      queryClient.invalidateQueries({ queryKey: ['pricing-card', cardQuery] })
    },
  })

  const refreshMutation = useMutation({
    mutationFn: () => apiPost(`/active/item/${encodeURIComponent(itemId!)}/refresh`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['active-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['active-list'] })
      queryClient.invalidateQueries({ queryKey: ['active-item-positions', itemId] })
      queryClient.invalidateQueries({ queryKey: ['pricing-comparisons'] })
      queryClient.invalidateQueries({ queryKey: ['pricing-card', cardQuery] })
    },
  })

  const startEditingPrice = () => {
    setPriceInput(item?.Price != null ? String(item.Price) : '')
    revisePriceMutation.reset()
    setEditingPrice(true)
  }

  const submitPrice = () => {
    const parsed = Number(priceInput)
    if (!Number.isFinite(parsed) || parsed <= 0) return
    revisePriceMutation.mutate(parsed)
  }

  const cardQuery = item?.Card || item?.Title || ''
  const { data: cardDetail, isLoading: cardLoading } = useQuery<CardPriceDetail>({
    queryKey: ['pricing-card', cardQuery],
    queryFn: () => api(`/pricing/cards/${encodeURIComponent(cardQuery)}`),
    enabled: !!cardQuery,
  })

  const { data: comparisons } = useQuery<PriceComparison[]>({
    queryKey: ['pricing-comparisons'],
    queryFn: () => api('/pricing/comparisons'),
  })

  const { data: positions } = useQuery<PositionHistoryPoint[]>({
    queryKey: ['active-item-positions', itemId],
    queryFn: () => api(`/active/item/${encodeURIComponent(itemId!)}/positions`),
    enabled: !!itemId,
  })

  // The exact active_price_snapshots card_query this listing resolved to (possibly
  // fuzzy-matched), so this page reads the same comp figures the list page shows
  // rather than re-deriving a mean that could disagree for the same card.
  const comparison = comparisons?.find((c) => c.card_query === cardDetail?.card_query)

  const activeSnaps = (cardDetail?.active_snapshots ?? []).map((s) => ({
    ...s,
    date: s.snapshot_date?.slice(5),
  })).reverse()

  const priceHistory: PriceHistoryPoint[] = []
  for (const a of activeSnaps) {
    const row = priceHistory.find((r) => r.date === a.date)
    const active = a.avg_price ?? undefined
    if (row) row.active = active
    else priceHistory.push({ date: a.date, active })
  }
  priceHistory.sort((a, b) => a.date.localeCompare(b.date))

  const recentActive = cardDetail?.recent_active ?? []
  const matchedNote = cardDetail?.matched_query ? `Showing data for: ${cardDetail.card_query}` : null

  const positionHistory = (positions ?? []).map((p) => ({
    date: p.snapshot_date.slice(5),
    position: p.position,
  }))

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonHeader />
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-7 gap-4">
          {Array.from({ length: 7 }).map((_, i) => <KpiSkeleton key={i} />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartSkeleton height={200} />
          <ChartSkeleton height={200} />
        </div>
        <TableSkeleton rows={5} columns={[{ header: 'Title', width: 'w-72' }, { header: 'Price', width: 'w-16' }]} />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="space-y-4">
        <Link to="/active" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} /> Back to Active Listings
        </Link>
        <div className="text-sm text-slate-400">Listing not found.</div>
      </div>
    )
  }

  // symbol:false is for the price card, which renders its own "$" in a fixed
  // position so the glyph doesn't shift as the number changes width.
  const money = (v: unknown, opts?: { symbol?: boolean }) => {
    if (v === null || v === undefined || v === '') return '—'
    const s = formatCurrency(v as string)
    return opts?.symbol === false ? s.replace(/^\$/, '') : s
  }
  const int = (v: unknown) => (v !== null && v !== undefined && v !== '' ? formatInt(v as string) : '—')
  const pct = (v: unknown) => {
    if (v === null || v === undefined || v === '') return '—'
    const s = String(v)
    return s.includes('%') ? s : `${s}%`
  }

  const priceNum = toNumber(item.Price)
  const shippingChargeNum = toNumber(item['Shipping Charge'])
  const totalPriceNum = priceNum !== null ? priceNum + (shippingChargeNum ?? 0) : null

  // Canonical, backend-computed benchmark figures (price_research.py) instead of
  // re-deriving them client-side, so this page always agrees with the Active
  // Listings list page for the same card.
  const priceAccuracyPct = (() => {
    const n = toNumber(item['Price Accuracy'])
    return n !== null ? n * 100 : null
  })()
  const activePrices = recentActive
    .map((r) => Number(r.price))
    .filter((n) => Number.isFinite(n))
  const activeAvg =
    comparison?.active_avg ?? (activePrices.length ? activePrices.reduce((a, b) => a + b, 0) / activePrices.length : null)
  const activeMin = activePrices.length ? Math.min(...activePrices) : null
  const activeMax = activePrices.length ? Math.max(...activePrices) : null

  // Item price alone understates what a buyer actually pays - rank comps by the
  // all-in total so the cheapest *landed* price surfaces first, not just cheapest item.
  const compsWithTotal = recentActive.map((r) => {
    const price = Number(r.price)
    const hasPrice = Number.isFinite(price)
    const shipping = r.shipping_cost != null ? Number(r.shipping_cost) : null
    const hasShipping = shipping !== null && Number.isFinite(shipping)
    return {
      ...r,
      _total: hasPrice ? price + (hasShipping ? shipping : 0) : null,
      _hasShipping: hasShipping,
    }
  })
  const sortedComps = [...compsWithTotal].sort((a, b) => {
    if (a._total === null) return 1
    if (b._total === null) return -1
    return a._total - b._total
  })
  const bestTotal = sortedComps.length && sortedComps[0]._total !== null ? sortedComps[0]._total : null

  const knownShippingCosts = compsWithTotal.filter((r) => r._hasShipping).map((r) => Number(r.shipping_cost))
  const avgShipping = knownShippingCosts.length
    ? knownShippingCosts.reduce((a, b) => a + b, 0) / knownShippingCosts.length
    : null

  const rawItemId = typeof item['Item ID'] === 'string' ? item['Item ID'].trim() : ''
  const ebayUrl = rawItemId ? `https://www.ebay.com/itm/${rawItemId}` : null

  const rankNum = toNumber(item['Search Position'])
  const watchersNum = toNumber(item.Watchers)

  // Read the stored, server-computed suggestion. Both this page and the list page read
  // this same field, so they can no longer disagree the way the old client-side
  // calculation did.
  const recommendedPrice = toNumber(item['Suggested Price'])
  const suggestionBasis = (item['Suggested Price Basis'] as SuggestedPriceBasis | null) ?? null
  const recommendationDiffers =
    recommendedPrice !== null && (priceNum === null || Math.abs(recommendedPrice - priceNum) >= 0.01)

  const useRecommendedPrice = () => {
    if (recommendedPrice === null) return
    setPriceInput(recommendedPrice.toFixed(2))
    revisePriceMutation.reset()
    setEditingPrice(true)
  }

  const lastChecked = (item['Last Checked'] as string) || null
  const daysSinceChecked = lastChecked
    ? Math.floor((Date.now() - new Date(`${lastChecked}T00:00:00Z`).getTime()) / 86_400_000)
    : null
  const freshnessClass =
    daysSinceChecked === null || daysSinceChecked >= 7
      ? 'text-rose-600 dark:text-rose-400'
      : daysSinceChecked >= 2
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-emerald-600 dark:text-emerald-400'

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-4">
        <Link
          to="/active"
          className="group inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline"
        >
          <ArrowLeft size={14} className="transition-transform group-hover:-translate-x-0.5" />
          Back to Active Listings
        </Link>
        <div className="flex flex-col items-end gap-0.5">
          <button
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-slate-700 dark:text-neutral-200 text-sm font-medium rounded-lg hover:bg-slate-50 dark:hover:bg-neutral-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={14} className={refreshMutation.isPending ? 'animate-spin' : ''} />
            {refreshMutation.isPending ? 'Refreshing…' : 'Refresh This Card'}
          </button>
          {refreshMutation.isError && (
            <p className="text-xs text-rose-600 dark:text-rose-400">
              {(refreshMutation.error as Error).message}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Header */}
      {editingCard && (
        <CardMatchDialog
          itemId={itemId!}
          current={(item.Card as string) ?? null}
          locked={!!item['Card Locked']}
          onClose={() => setEditingCard(false)}
        />
      )}

      <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex flex-col">
        {/* Image beside one content column, rather than three flex children that
            wrap: this card sits in a half-width grid column, and the price block
            used to wrap onto its own line still carrying the left border that only
            made sense while it sat beside the title. */}
        {/* items-start, not items-stretch: the art used to take its size from the
            content column beside it (h-full + self-stretch), so the more a listing
            had to say, the taller its card grew. A card is a fixed shape - give it
            a width and let 5/7 settle the rest. */}
        <div className="flex flex-1 items-start gap-5">
          {item.card_image_url && !artFailed ? (
            <img
              src={item.card_image_url}
              alt={`${item.Card ?? item.Title} card`}
              loading="lazy"
              // Swapped for the card back rather than hidden: a vanishing image
              // left a gap the layout had already reserved.
              onError={() => setArtFailed(true)}
              className="aspect-[5/7] w-32 sm:w-40 shrink-0 rounded-lg object-contain"
            />
          ) : (
            <CardBack className="w-32 sm:w-40 rounded-lg" />
          )}

          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100 leading-snug tracking-tight">
              {item.Title}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              {item.Condition && (
                <span className="text-xs text-slate-500 dark:text-neutral-400">{item.Condition}</span>
              )}
              {/* The catalog match, and the way to fix it. It decides which card
                  the listing is priced against, so a wrong one is a wrong price -
                  it should not be a read-only fact on the page. */}
              <button
                onClick={() => setEditingCard(true)}
                className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-neutral-400 hover:text-slate-800 dark:hover:text-neutral-200"
                title="Change which card this is priced against"
              >
                {item.Card || <span className="italic">no catalog match</span>}
                {item['Card Locked'] && (
                  <span className="rounded px-1 py-0.5 text-[10px] font-medium bg-slate-100 dark:bg-neutral-700">
                    manual
                  </span>
                )}
                <Pencil size={11} />
              </button>
              {/* An action, not a stat - it used to occupy a cell in the label/value
                  grid below, where having no label left it sitting half a line above
                  every neighbouring value. */}
              {ebayUrl && (
                <a
                  href={ebayUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline"
                >
                  View on eBay
                  <ExternalLink size={11} />
                </a>
              )}
            </div>

            <div className="mt-4 border-t border-slate-100 dark:border-neutral-700 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Price</p>

              {/* Fixed height + shared baseline: no jump between modes */}
              <div className="mt-1 flex h-12 items-baseline gap-1.5">
                <span className="text-2xl font-semibold text-slate-400">$</span>
                {editingPrice ? (
                  <>
                    <input
                      type="number" step="0.01" min="0.01" autoFocus
                      value={priceInput}
                      onChange={(e) => setPriceInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') submitPrice()
                        if (e.key === 'Escape') setEditingPrice(false)
                      }}
                      aria-label="New price"
                      className="w-[6ch] border-b-2 border-blue-500 bg-transparent text-4xl font-bold tabular-nums text-slate-900 focus:outline-none dark:text-neutral-100 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                    />
                    <span className="ml-2 flex items-center gap-1 self-center">
                      <button onClick={submitPrice} disabled={revisePriceMutation.isPending} aria-label="Save price"
                        className="rounded-md p-1.5 text-emerald-600 hover:bg-emerald-50 disabled:opacity-50 dark:hover:bg-emerald-500/15">
                        {revisePriceMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                      </button>
                      <button onClick={() => setEditingPrice(false)} disabled={revisePriceMutation.isPending} aria-label="Cancel"
                        className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-neutral-700">
                        <X size={16} />
                      </button>
                    </span>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={startEditingPrice}
                    title="Click to edit price"
                    aria-label={`Revise price on eBay, currently ${money(item.Price)}`}
                    className="-mx-1 rounded-md px-1 text-4xl font-bold tracking-tight tabular-nums text-slate-900 hover:bg-slate-100 dark:text-neutral-100 dark:hover:bg-neutral-700"
                  >
                    {money(item.Price, { symbol: false })}
                  </button>
                )}
              </div>

              {/* One chip row, reserved height, same visual weight for both signals */}
              <div className="mt-2 flex min-h-[22px] flex-wrap items-center gap-x-2 gap-y-1.5">
                {priceAccuracyPct !== null && (
                  <span className={`${chip} ${priceAccuracyPct <= 0
                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                    : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'}`}>
                    {priceAccuracyPct <= 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
                    {Math.abs(priceAccuracyPct).toFixed(1)}% {priceAccuracyPct <= 0 ? 'below' : 'above'} market
                  </span>
                )}
                {!editingPrice && recommendedPrice !== null && recommendationDiffers && (
                  <button
                    onClick={useRecommendedPrice}
                    title={formatSuggestionReason(suggestionBasis)}
                    className={`${chip} bg-blue-50 text-blue-700 hover:bg-blue-100 dark:bg-blue-500/15 dark:text-blue-300 dark:hover:bg-blue-500/25`}
                  >
                    {/* One number, and it is the one a click applies. The clamped
                        model target (basis.pre_guardrail) used to sit here behind an
                        arrow, which read as the price being offered - it is in the
                        tooltip instead, where formatSuggestionReason already names
                        the guardrail that held the suggestion back. */}
                    Use {formatCurrency(recommendedPrice)}
                  </button>
                )}
              </div>

              {revisePriceMutation.isError && (
                <p className="mt-1.5 text-xs text-rose-600 dark:text-rose-400">
                  {(revisePriceMutation.error as Error).message}
                </p>
              )}
            </div>
            <div className="mt-4 grid grid-cols-2 xl:grid-cols-3 gap-x-4 gap-y-3 text-sm">
              <div>
                <p className="text-xs text-slate-400">Start Date</p>
                <p className="text-slate-700 dark:text-neutral-200 font-medium">{(item['Start Date'] as string) || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400">Watchers</p>
                <p className={cn(
                  'font-medium tabular-nums',
                  watchersNum ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-700 dark:text-neutral-200',
                )}>
                  {watchersNum ?? 0}
                </p>
              </div>
              {toNumber(item.Quantity) !== null && toNumber(item.Quantity)! > 1 && (
                <div>
                  <p className="text-xs text-slate-400">Quantity</p>
                  <p className="text-slate-700 dark:text-neutral-200 font-medium tabular-nums">{int(item.Quantity)}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-slate-400">Ad Rate</p>
                <p className="text-slate-700 dark:text-neutral-200 font-medium tabular-nums">{pct(item['Ad Rate'])}</p>
              </div>
              {item.SKU && (
                <div>
                  <p className="text-xs text-slate-400">SKU</p>
                  <p className="text-slate-700 dark:text-neutral-200 font-medium">{item.SKU as string}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-slate-400">Shipping Charge</p>
                <p className="text-slate-700 dark:text-neutral-200 font-medium tabular-nums">{money(item['Shipping Charge'])}</p>
              </div>
              <div>
                <p className="text-xs text-slate-400">Total (incl. shipping)</p>
                <p className="text-slate-700 dark:text-neutral-200 font-medium tabular-nums">
                  {totalPriceNum !== null ? formatCurrency(totalPriceNum) : '—'}
                </p>
              </div>
              {rankNum !== null && (
                <div>
                  <p className="text-xs text-slate-400">Search Rank</p>
                  <div className="flex items-center gap-2">
                    <p className="text-slate-700 dark:text-neutral-200 font-medium tabular-nums">#{rankNum}</p>
                    {positionHistory.length > 1 && (
                      <div className="h-6 w-16" title="Search rank, last 90 days">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={positionHistory}>
                            <Line type="monotone" dataKey="position" stroke="#94a3b8" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div>
                <p className="text-xs text-slate-400">Last Checked</p>
                <p className={`font-medium inline-flex items-center gap-1 ${freshnessClass}`}>
                  <Clock size={11} />
                  {lastChecked
                    ? daysSinceChecked === 0
                      ? 'Today'
                      : `${daysSinceChecked}d ago`
                    : 'Never'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Price history */}
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex flex-col">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 mb-1">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200">Price History</h2>
          {priceHistory.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 justify-end">
              <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-neutral-400">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> Active avg
              </span>
              {priceNum !== null && (
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-neutral-400">
                  <span className="h-0.5 w-3 border-t-2 border-dashed border-amber-500" /> Listed price
                </span>
              )}
            </div>
          )}
        </div>
        {matchedNote && <p className="text-xs text-slate-400 mb-2">{matchedNote}</p>}
        {/* Fills the column rather than sitting at a fixed height. This card is grid-
            stretched alongside the header, so when the card image grew the header got
            taller, the chart stayed at 220px and left dead space beneath it. min-h keeps
            the original size on the single-column layout, where there is nothing to
            stretch against. */}
        <div className="flex-1 min-h-[220px]">
        {cardLoading ? (
          <ChartSkeleton height={220} />
        ) : priceHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={priceHistory}>
              <CartesianGrid vertical={false} stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
              <Tooltip
                cursor={cursor.line}
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const activeAvg = payload.find((p) => p.dataKey === 'active')?.value
                  if (activeAvg == null) return null
                  return (
                    <div className="bg-white dark:bg-neutral-800 border border-slate-200 dark:border-neutral-700 rounded-md shadow-sm px-3 py-2 text-xs space-y-0.5">
                      <p className="font-semibold text-slate-700 dark:text-neutral-200 mb-1">{label}</p>
                      {activeAvg != null && <p className="text-emerald-600 dark:text-emerald-400">Active avg: {formatCurrency(Number(activeAvg))}</p>}
                    </div>
                  )
                }}
              />
              {priceNum !== null && (
                <ReferenceLine
                  y={priceNum}
                  stroke="#f59e0b"
                  strokeDasharray="4 4"
                  label={{ value: `Listed $${priceNum.toFixed(2)}`, position: 'insideTopLeft', fill: '#b45309', fontSize: 10 }}
                />
              )}
              <Line type="monotone" dataKey="active" stroke="#10b981" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <EmptyChart label="No price history." />
        )}
        </div>
      </div>
      </div>

      {/* Competing listings for this card, currently active on eBay */}
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200">Competing Listings</h2>
        </div>
        {cardLoading ? (
          <TableSkeleton rows={5} columns={[{ header: 'Title', width: 'w-72' }, { header: 'Price', width: 'w-16' }]} />
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
              <KpiCard title="Active Count" value={int(recentActive.length)} />
              <KpiCard title="Active Avg" value={activeAvg !== null ? formatCurrency(activeAvg) : '—'} />
              <KpiCard title="Active Min" value={activeMin !== null ? formatCurrency(activeMin) : '—'} />
              <KpiCard title="Active Max" value={activeMax !== null ? formatCurrency(activeMax) : '—'} />
              <KpiCard title="Avg Shipping" value={avgShipping !== null ? formatCurrency(avgShipping) : '—'} />
            </div>
            {sortedComps.length > 0 ? (
              <DataTable
                columns={[
                  {
                    key: 'title',
                    header: 'Listing',
                    className: 'max-w-sm',
                    render: (r) => (
                      <div>
                        <div className="truncate font-medium text-slate-800 dark:text-neutral-100">{r.title as string}</div>
                        <div className="text-[11px] text-slate-400">{formatShortDate(r.pulled_at as string)}</div>
                      </div>
                    ),
                  },
                  {
                    key: 'price',
                    header: 'Price',
                    className: 'w-20',
                    render: (r) => <span className="tabular-nums">{formatCurrency(r.price as string)}</span>,
                  },
                  {
                    key: 'shipping_cost',
                    header: 'Shipping',
                    className: 'w-24',
                    // Browse API only returns this for listings it could estimate cost for
                    // (and estimates against a default location, not this specific buyer) -
                    // absent is shown as unknown rather than implying free shipping.
                    render: (r) =>
                      r.shipping_cost != null ? (
                        <span className="tabular-nums text-slate-500 dark:text-neutral-400">{formatCurrency(r.shipping_cost as string)}</span>
                      ) : (
                        <span className="text-slate-300 dark:text-neutral-600" title="Shipping cost not returned for this listing">n/a</span>
                      ),
                  },
                  {
                    key: '_total',
                    header: 'Total',
                    className: 'w-28',
                    render: (r) => {
                      const total = r._total as number | null
                      if (total === null) return <span className="text-slate-400">—</span>
                      const isBest = bestTotal !== null && Math.abs(total - bestTotal) < 0.005
                      return (
                        <span
                          className={`tabular-nums font-semibold ${isBest ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-800 dark:text-neutral-100'}`}
                          title={isBest ? 'Lowest total price (item + shipping) among these comps' : undefined}
                        >
                          {formatCurrency(total)}
                        </span>
                      )
                    },
                  },
                  { key: 'url', header: '', className: 'w-8', render: renderListingLink },
                ]}
                data={sortedComps as Record<string, unknown>[]}
              />
            ) : (
              <div className="flex h-28 flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200 dark:border-neutral-700 text-slate-400">
                <PackageSearch size={20} strokeWidth={1.5} />
                <p className="text-sm">No other active listings found.</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function SkeletonHeader() {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 flex items-start gap-5">
      <div className="w-24 h-24 rounded-lg bg-slate-200 dark:bg-neutral-700 animate-pulse shrink-0" />
      <div className="space-y-2 w-full">
        <div className="h-6 w-3/4 bg-slate-200 dark:bg-neutral-700 animate-pulse rounded-md" />
        <div className="h-4 w-40 bg-slate-200 dark:bg-neutral-700 animate-pulse rounded-md" />
      </div>
    </div>
  )
}