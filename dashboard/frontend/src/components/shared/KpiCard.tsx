import type { ReactNode } from 'react'

interface KpiCardProps {
  title: string
  value: string
  subtitle?: string
  icon?: ReactNode
}

export function KpiCard({ title, value, subtitle, icon }: KpiCardProps) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-4 flex items-center gap-4 shadow-sm">
      {icon && <div className="text-slate-400">{icon}</div>}
      <div>
        <p className="text-xs text-slate-500 dark:text-neutral-400 uppercase tracking-wide font-medium">{title}</p>
        <p className="text-2xl font-bold text-slate-900 dark:text-neutral-100 mt-0.5">{value}</p>
        {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  )
}
