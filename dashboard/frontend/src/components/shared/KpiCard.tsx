import type { ReactNode } from 'react'

type KpiTone = 'default' | 'positive' | 'negative'

interface KpiCardProps {
  title: string
  value: string
  subtitle?: string
  icon?: ReactNode
  /** Colors the value text - 'positive'/'negative' for at-a-glance good/bad signals (e.g. price vs. benchmark). */
  tone?: KpiTone
}

const TONE_VALUE_CLASSES: Record<KpiTone, string> = {
  default: 'text-slate-900 dark:text-neutral-100',
  positive: 'text-emerald-600 dark:text-emerald-400',
  negative: 'text-amber-600 dark:text-amber-400',
}

export function KpiCard({ title, value, subtitle, icon, tone = 'default' }: KpiCardProps) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl p-4 flex items-center gap-4">
      {icon && <div className="text-slate-400">{icon}</div>}
      <div>
        <p className="text-xs text-slate-500 dark:text-neutral-400 uppercase tracking-wide font-medium">{title}</p>
        <p className={`text-2xl font-bold mt-0.5 ${TONE_VALUE_CLASSES[tone]}`}>{value}</p>
        {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  )
}
