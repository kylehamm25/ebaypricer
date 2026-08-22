import { Fragment, type ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

interface Column<T> {
  key: string
  header: ReactNode
  render?: (item: T) => ReactNode
  className?: string
  stopRowClick?: boolean
  /** Backend sort key this header sorts by. Presence alone makes the header clickable. */
  sortKey?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField?: string
  expandedRows?: Set<string>
  onToggleExpand?: (key: string) => void
  renderExpanded?: (item: T) => ReactNode
  onRowClick?: (item: T) => void
  /** Omit the separator above this row, merging it into the row above - used to
   *  show consecutive rows as one block. Never applies to the first row, which
   *  has no separator anyway. */
  hideRowDivider?: (item: T, index: number) => boolean
  hideHeader?: boolean
  sortBy?: string
  sortDir?: 'asc' | 'desc'
  onSortChange?: (sortKey: string) => void
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  expandedRows = new Set(),
  onToggleExpand,
  renderExpanded,
  onRowClick,
  hideRowDivider,
  hideHeader = false,
  sortBy,
  sortDir = 'desc',
  onSortChange,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-8 text-center text-slate-400 text-sm">
        No data
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl bg-white dark:bg-neutral-800">
      <table className="w-full text-sm">
        {!hideHeader && (
          <thead>
            <tr className="bg-slate-50 dark:bg-neutral-800/60 border-b border-slate-200 dark:border-neutral-700">
              {columns.map((col) => {
                const sortable = !!col.sortKey && !!onSortChange
                const active = sortable && col.sortKey === sortBy
                return (
                  <th
                    key={col.key}
                    className={`px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-neutral-400 uppercase tracking-wider ${col.className || ''}`}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        className={`inline-flex items-center gap-1 hover:text-slate-700 dark:hover:text-neutral-200 ${active ? 'text-slate-700 dark:text-neutral-200' : ''}`}
                        onClick={() => onSortChange?.(col.sortKey as string)}
                      >
                        {col.header}
                        {active ? (
                          sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                        ) : (
                          <ChevronsUpDown size={12} className="text-slate-300 dark:text-neutral-600" />
                        )}
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                )
              })}
              {(onToggleExpand || renderExpanded) && (
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-neutral-400 uppercase tracking-wider">
                  Actions
                </th>
              )}
            </tr>
          </thead>
        )}
        {/* The row separator is a per-row border rather than `divide-y` on the
            tbody: divide-y's selector outranks a single utility class, so a row
            could not opt out of it. Here an omitted row simply never gets the
            class, which is what hideRowDivider needs. */}
        <tbody>
          {data.map((item, i) => {
            const key = item[keyField || 'id'] as string || i.toString()
            const isExpanded = expandedRows.has(key)
            const divider = i > 0 && !hideRowDivider?.(item, i)
            return (
              // Keyed on the row's own id, not the index: without a key on the
              // fragment React can't match rows across renders, so re-sorting
              // rebuilt every row's DOM instead of reordering it.
              <Fragment key={key}>
                <tr
                  className={`hover:bg-slate-50 dark:hover:bg-neutral-700/50 transition-colors ${divider ? 'border-t border-slate-100 dark:border-neutral-700' : ''} ${isExpanded ? 'bg-blue-50 dark:bg-neutral-700/40' : ''} ${onRowClick ? 'cursor-pointer' : ''}`}
                  onClick={() => (onRowClick ? onRowClick(item) : onToggleExpand?.(key))}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-2.5 text-slate-700 dark:text-neutral-200 ${col.className || ''}`}
                      onClick={col.stopRowClick ? (e) => e.stopPropagation() : undefined}
                    >
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
                  <tr>
                    <td colSpan={columns.length + 1} className="px-0 py-0">
                      <div className="bg-slate-50 dark:bg-neutral-800/60 border-t border-slate-200 dark:border-neutral-700 p-4">
                        {renderExpanded(item)}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}