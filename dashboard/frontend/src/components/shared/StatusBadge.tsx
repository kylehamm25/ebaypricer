import { cn } from '../../lib/utils'

interface StatusBadgeProps {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const isRunning = status === 'running'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium',
        isRunning ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-green-100 text-green-800 dark:bg-green-500/20 dark:text-green-300'
      )}
    >
      <span
        className={cn(
          'w-1.5 h-1.5 rounded-full',
          isRunning ? 'bg-amber-500 animate-pulse' : 'bg-green-500'
        )}
      />
      {isRunning ? 'Running' : 'Idle'}
    </span>
  )
}
