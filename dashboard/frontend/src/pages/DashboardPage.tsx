import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar,
} from 'recharts'
import { Loader2, Play } from 'lucide-react'

import { api, apiPost } from '../lib/api'
import { KpiCard } from '../components/shared/KpiCard'
import { formatCurrency, formatInt } from '../lib/utils'
import type { DashboardKpis } from '../types'

// Formats a "YYYY-MM-DD" string as "Jul 10"
function formatShortDate(dateStr: string) {
  const [year, month, day] = dateStr.split('-').map(Number)
  const d = new Date(year, month - 1, day)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Computes a tick interval so at most `maxTicks` labels are shown
function getTickInterval(dataLength: number, maxTicks = 10) {
  if (dataLength <= maxTicks) return 0
  return Math.ceil(dataLength / maxTicks) - 1
}

export function DashboardPage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<DashboardKpis>({
    queryKey: ['dashboard-kpis'],
    queryFn: () => api('/dashboard/kpis'),
    refetchInterval: 60_000,
  })

  const [pStatus, setPStatus] = useState<'idle' | 'running'>('idle')
  const [lastRunAt, setLastRunAt] = useState<string | null>(null)

  const poll = async () => {
    try {
      const s = await api<{ state: string; finished_at: string | null }>('/pipeline/status')
      setPStatus(s.state === 'running' ? 'running' : 'idle')
      if (s.finished_at) setLastRunAt(s.finished_at)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    poll()
    const interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
  }, [])

  const runMutation = useMutation({
    mutationFn: () => apiPost('/pipeline/run'),
    onSuccess: () => {
      setPStatus('running')
      setTimeout(poll, 2000)
    },
  })

  if (isLoading || !data) {
    return <div className="text-slate-400 text-sm">Loading dashboard...</div>
  }

  return (
    <div className="relative space-y-6">
      {pStatus === 'running' && (
        <div className="absolute inset-0 z-10 bg-white/70 flex flex-col items-center justify-center rounded-xl" style={{ minHeight: '60vh' }}>
          <Loader2 size={40} className="text-blue-500 animate-spin mb-4" />
          <p className="text-sm text-slate-600 font-medium">Pipeline running...</p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <div className="flex items-center gap-3">
          {lastRunAt && (
            <span className="text-xs text-slate-500">
              Last run: {new Date(lastRunAt).toLocaleString()}
            </span>
          )}
          <button
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={pStatus === 'running' || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            {runMutation.isPending ? 'Starting...' : 'Run Pipeline'}
          </button>
        </div>
      </div>

      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wide font-medium mb-3">{new Date().toLocaleString('en-US', { month: 'long' })}</p>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
          <KpiCard title="Items Sold" value={formatInt(data.sold_items)} />
          <KpiCard title="Total Revenue" value={formatCurrency(data.revenue)} />
          <KpiCard title="eBay Fees" value={formatCurrency(data.fees)} />
          <KpiCard title="Order Earnings" value={formatCurrency(data.revenue - data.fees)} />
          <KpiCard title="Active Listings" value={formatInt(data.active_listings)} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="lg:col-span-1 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Daily Orders</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={data.trends}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={getTickInterval(data.trends.length)} tickFormatter={formatShortDate} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip labelFormatter={formatShortDate} />
              <Bar dataKey="count" fill="#3b82f6" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Daily Revenue</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={data.trends}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={getTickInterval(data.trends.length)} tickFormatter={formatShortDate} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => '$' + Number(v).toFixed(2)} labelFormatter={formatShortDate} />
              <Bar dataKey="revenue" fill="#10b981" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
