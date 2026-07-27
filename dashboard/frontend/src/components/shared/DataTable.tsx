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
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  expandedRows = new Set(),
  onToggleExpand,
  renderExpanded,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">
        No data
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider"
              >
                {col.header}
              </th>
            ))}
            {(onToggleExpand || renderExpanded) && (
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                Actions
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.map((item, i) => {
            const key = item[keyField || 'id'] as string || i.toString()
            const isExpanded = expandedRows.has(key)
            return (
              <>
                <tr
                  key={i}
                  className={`hover:bg-slate-50 transition-colors cursor-pointer ${isExpanded ? 'bg-blue-50' : ''}`}
                  onClick={() => onToggleExpand?.(key)}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={`px-4 py-2.5 text-slate-700 ${col.className || ''}`}>
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
                      <div className="bg-slate-50 border-t border-slate-200 p-4">
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