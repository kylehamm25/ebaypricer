import type { ReactNode } from 'react'

interface Column<T> {
  key: string
  header: string
  render?: (item: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField?: string
  expandedRows?: Set<string>
  onToggleExpand?: (key: string) => void
  renderExpanded?: (item: T) => ReactNode
  onRowClick?: (item: T) => void
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  expandedRows = new Set(),
  onToggleExpand,
  renderExpanded,
  onRowClick,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-slate-200 dark:border-neutral-700 p-8 text-center text-slate-400 text-sm">
        No data
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-neutral-700 bg-white dark:bg-neutral-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 dark:bg-neutral-800/60 border-b border-slate-200 dark:border-neutral-700">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-neutral-400 uppercase tracking-wider"
              >
                {col.header}
              </th>
            ))}
            {(onToggleExpand || renderExpanded) && (
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-neutral-400 uppercase tracking-wider">
                Actions
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-neutral-700">
          {data.map((item, i) => {
            const key = item[keyField || 'id'] as string || i.toString()
            const isExpanded = expandedRows.has(key)
            return (
              <>
                <tr
                  key={i}
                  className={`hover:bg-slate-50 dark:hover:bg-neutral-700/50 transition-colors ${isExpanded ? 'bg-blue-50 dark:bg-neutral-700/40' : ''} ${onRowClick ? 'cursor-pointer' : ''}`}
                  onClick={() => (onRowClick ? onRowClick(item) : onToggleExpand?.(key))}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={`px-4 py-2.5 text-slate-700 dark:text-neutral-200 ${col.className || ''}`}>
                      {col.render ? col.render(item) : String(item[col.key] ?? '')}
                    </td>
                  ))}
                  {(onToggleExpand || renderExpanded) && (
                    <td className="px-4 py-2.5 text-slate-400">
                      {isExpanded ? '▲' : '▼'}
                    </td>
                  )}
                </tr>
                {isExpanded && renderExpanded && (
                  <tr key={`expanded-${i}`}>
                    <td colSpan={columns.length + 1} className="px-0 py-0">
                      <div className="bg-slate-50 dark:bg-neutral-800/60 border-t border-slate-200 dark:border-neutral-700 p-4">
                        {renderExpanded(item)}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}