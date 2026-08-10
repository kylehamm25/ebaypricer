import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { api, apiPost } from '../../lib/api'

interface RefreshStatus {
  state: 'idle' | 'running'
  last_run_at: string | null
}

interface Props {
  /** GET path returning { state, last_run_at } for this stage's job_runs row. */
  statusPath: string
  /** POST path that starts the stage in the background. */
  runPath: string
  label: string
  /** Called once, right when a running refresh transitions back to idle. */
  onRefreshed?: () => void
}

export function StageRefreshButton({ statusPath, runPath, label, onRefreshed }: Props) {
  const [status, setStatus] = useState<'idle' | 'running'>('idle')
  const [lastRunAt, setLastRunAt] = useState<string | null>(null)
  const wasRunning = useRef(false)

  const poll = async () => {
    try {
      const s = await api<RefreshStatus>(statusPath)
      const running = s.state === 'running'
      if (wasRunning.current && !running) onRefreshed?.()
      wasRunning.current = running
      setStatus(running ? 'running' : 'idle')
      if (s.last_run_at) setLastRunAt(s.last_run_at)
    } catch {
      // ignore transient poll failures
    }
  }

  useEffect(() => {
    poll()
    const interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusPath])

  const runMutation = useMutation({
    mutationFn: () => apiPost(runPath),
    onSuccess: () => {
      wasRunning.current = true
      setStatus('running')
      setTimeout(poll, 2000)
    },
  })

  const busy = status === 'running' || runMutation.isPending

  return (
    <div className="flex items-center gap-3">
      {lastRunAt && !busy && (
        <span className="text-xs text-slate-500 dark:text-neutral-400">
          Last refreshed: {new Date(lastRunAt).toLocaleString()}
        </span>
      )}
      <button
        className="inline-flex items-center gap-2 px-3 py-1.5 border border-slate-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-slate-700 dark:text-neutral-200 text-sm font-medium rounded-lg hover:bg-slate-50 dark:hover:bg-neutral-700 disabled:opacity-50 disabled:cursor-not-allowed"
        disabled={busy}
        onClick={() => runMutation.mutate()}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        {status === 'running' ? 'Refreshing...' : runMutation.isPending ? 'Starting...' : label}
      </button>
    </div>
  )
}
