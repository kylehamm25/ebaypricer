import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { DataTable } from '../components/shared/DataTable'
import { TableSkeleton, Skeleton } from '../components/shared/Skeleton'

export function PromotionsPage() {
  const { data: campaigns, isLoading: campLoading } = useQuery({
    queryKey: ['campaigns'],
    queryFn: () => api('/promotions/campaigns'),
    refetchInterval: 300_000,
  })

  const { data: ads, isLoading: adsLoading } = useQuery({
    queryKey: ['ads'],
    queryFn: () => api('/promotions/ads'),
    refetchInterval: 300_000,
  })

  const campList = Array.isArray(campaigns) ? campaigns : []
  const adList = Array.isArray(ads) ? ads : []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Promotions</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {campLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 shadow-sm space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-28" />
              </div>
            ))}
          </div>
        ) : campList.length === 0 ? (
          <div className="text-sm text-slate-400">No campaigns found.</div>
        ) : (
          campList.map((c: Record<string, unknown>) => (
            <div key={c.campaignId as string} className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 shadow-sm">
              <h3 className="font-semibold text-slate-800 dark:text-neutral-100 text-sm">{c.campaignName as string}</h3>
              <div className="mt-2 space-y-1 text-xs text-slate-500">
                <p>ID: {(c.campaignId as string)?.slice(0, 12)}...</p>
                <p>Status: {c.campaignStatus as string}</p>
                <p>Model: {(c.fundingModel as string) ?? (c.fundingStrategy as Record<string, unknown>)?.fundingModel as string ?? '—'}</p>
              </div>
            </div>
          ))
        )}
      </div>

      <div>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-neutral-200 mb-3">Ad Rates</h2>
        {adsLoading ? (
          <TableSkeleton
            rows={6}
            columns={[
              { header: 'Listing ID', width: 'w-24' },
              { header: 'Bid %', width: 'w-12' },
              { header: 'Campaign', width: 'w-32' },
            ]}
          />
        ) : adList.length === 0 ? (
          <div className="text-sm text-slate-400">No ad data available.</div>
        ) : (
          <DataTable
            columns={[
              { key: 'listingId', header: 'Listing ID' },
              {
                key: 'bidPercentage',
                header: 'Bid %',
                render: (r) => {
                  const v = r.bidPercentage as number
                  return v != null ? `${v.toFixed(1)}%` : '—'
                },
              },
              { key: 'campaign_name', header: 'Campaign' },
            ]}
            data={adList as unknown as Record<string, unknown>[]}
          />
        )}
      </div>
    </div>
  )
}
