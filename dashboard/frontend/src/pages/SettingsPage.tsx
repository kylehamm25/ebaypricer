import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link2, Link2Off, Loader2, CheckCircle2 } from 'lucide-react'
import { api, apiPost } from '../lib/api'
import type { EbayStatus } from '../types'
import { ApiUsageBar } from '../components/shared/ApiUsageBar'

export function SettingsPage() {
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const justConnected = new URLSearchParams(window.location.search).get('ebay') === 'connected'

  const { data: status, isLoading, refetch } = useQuery<EbayStatus>({
    queryKey: ['ebay-status'],
    queryFn: () => api('/ebay/status'),
    refetchInterval: 30_000,
  })

  const handleConnect = async () => {
    setError(null)
    setConnecting(true)
    try {
      const { url } = await api<{ url: string }>('/ebay/connect-url')
      window.location.href = url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start eBay connection')
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    setError(null)
    try {
      await apiPost('/ebay/disconnect')
      await refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to disconnect')
    }
  }

  const scopes = status?.scopes?.split(' ') ?? []

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">Settings</h1>

      {justConnected && (
        <div className="flex items-center gap-2 p-4 rounded-md bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30">
          <CheckCircle2 size={18} />
          eBay account connected successfully.
        </div>
      )}
      {error && (
        <div className="p-4 rounded-md bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300 border border-red-200 dark:border-red-500/30">{error}</div>
      )}

      <div className="p-6 bg-white dark:bg-neutral-800 rounded-lg">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-neutral-100">eBay Account</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-neutral-400">
          Connect your eBay account to sync sold orders and finances.
        </p>

        {isLoading ? (
          <div className="mt-6 flex items-center gap-2 text-slate-400">
            <Loader2 size={18} className="animate-spin" /> Checking connection...
          </div>
        ) : status?.connected ? (
          <div className="mt-6 space-y-3">
            <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 size={18} />
              <span className="font-medium">Connected</span>
            </div>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <div>
                <dt className="text-slate-500 dark:text-neutral-400">eBay user ID</dt>
                <dd className="font-mono text-slate-900 dark:text-neutral-100">{status.ebay_user_id ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-slate-500 dark:text-neutral-400">Sync status</dt>
                <dd className="text-slate-900 dark:text-neutral-100">{status.sync_status ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-slate-500 dark:text-neutral-400">Token expires</dt>
                <dd className="text-slate-900 dark:text-neutral-100">
                  {status.token_expires_at
                    ? new Date(status.token_expires_at).toLocaleString()
                    : '—'}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500 dark:text-neutral-400">Last synced</dt>
                <dd className="text-slate-900 dark:text-neutral-100">
                  {status.last_synced_at ? new Date(status.last_synced_at).toLocaleString() : '—'}
                </dd>
              </div>
            </dl>
            <div>
              <dt className="text-sm text-slate-500 dark:text-neutral-400">Granted scopes</dt>
              <ul className="mt-1 text-xs text-slate-600 dark:text-neutral-300 space-y-0.5">
                {scopes.map((s) => (
                  <li key={s} className="font-mono truncate">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
            <button
              onClick={handleDisconnect}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              <Link2Off size={16} />
              Disconnect
            </button>
          </div>
        ) : (
          <div className="mt-6">
            <button
              onClick={handleConnect}
              disabled={connecting}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {connecting ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />}
              {connecting ? 'Redirecting to eBay...' : 'Connect eBay Account'}
            </button>
            <p className="mt-2 text-xs text-slate-400">
              You'll be taken to eBay to authorize read-only access to your orders and finances.
            </p>
          </div>
        )}
      </div>

      <ApiUsageBar />
    </div>
  )
}
