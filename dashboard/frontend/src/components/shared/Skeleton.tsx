import type { CSSProperties } from 'react'

export function Skeleton({ className = '', style }: { className?: string; style?: CSSProperties }) {
  return <div className={`animate-pulse bg-slate-200 dark:bg-neutral-700 rounded-md ${className}`} style={style} />
}

export function KpiSkeleton() {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 shadow-sm space-y-2">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-7 w-28" />
    </div>
  )
}

export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 shadow-sm">
      <Skeleton className="h-4 w-44 mb-3" />
      <Skeleton className="w-full" style={{ height }} />
    </div>
  )
}

export interface TableSkeletonColumn {
  header: string
  width?: string
}

export function TableSkeleton({ rows = 8, columns = [] }: { rows?: number; columns?: TableSkeletonColumn[] }) {
  const cols = columns.length > 0 ? columns : [{ header: '', width: 'w-full' }]
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-neutral-700 bg-white dark:bg-neutral-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 dark:bg-neutral-800/60 border-b border-slate-200 dark:border-neutral-700">
            {cols.map((c, i) => (
              <th key={i} className="px-4 py-3 text-left">
                {c.header !== '' && <Skeleton className={`h-2.5 ${c.width || 'w-16'}`} />}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-neutral-700">
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {cols.map((c, i) => (
                <td key={i} className="px-4 py-2.5">
                  {c.header === '' ? (
                    <Skeleton className="w-16 h-16 rounded" />
                  ) : (
                    <Skeleton className={`h-4 ${c.width || 'w-16'}`} />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
