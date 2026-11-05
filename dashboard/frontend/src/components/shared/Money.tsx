import { formatCurrency, profitTone } from '../../lib/utils'

export function Money({ value, bold }: { value: number | null | undefined; bold?: boolean }) {
  if (value == null) return <span className="text-slate-400 text-xs">—</span>
  return (
    <span className={`tabular-nums ${bold ? 'font-semibold' : ''} ${profitTone(value)}`}>
      {value > 0 ? '+' : ''}{formatCurrency(value)}
    </span>
  )
}
