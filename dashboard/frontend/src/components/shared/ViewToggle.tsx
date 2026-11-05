import { useState } from 'react'
import { LayoutGrid, List } from 'lucide-react'
import type { View } from '../../lib/view-preference'

export function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="flex items-center gap-1 bg-white dark:bg-neutral-800 rounded-lg p-1">
      {([['table', List], ['grid', LayoutGrid]] as const).map(([v, Icon]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          aria-label={v === 'table' ? 'Table view' : 'Grid view'}
          aria-pressed={view === v}
          className={`p-1.5 rounded-md ${
            view === v
              ? 'bg-slate-100 dark:bg-neutral-700 text-slate-900 dark:text-neutral-100'
              : 'text-slate-400 hover:text-slate-700 dark:hover:text-neutral-200'
          }`}
        >
          <Icon size={16} />
        </button>
      ))}
    </div>
  )
}

export function GridShell({ selected, onClick, label, children, dropActive, onDragEnter, onDragOver, onDragLeave, onDrop }: {
  selected?: boolean
  onClick?: (e?: React.MouseEvent) => void
  label?: string
  children: React.ReactNode
  dropActive?: boolean
  onDragEnter?: (e: React.DragEvent) => void
  onDragOver?: (e: React.DragEvent) => void
  onDragLeave?: (e: React.DragEvent) => void
  onDrop?: (e: React.DragEvent) => void
}) {
  // `group` so a tile's inner panels can tint along with it - a highlight that
  // stops at the artwork's edge reads as a bug rather than a hover state.
  const base = 'group flex flex-col overflow-hidden rounded-xl bg-white dark:bg-neutral-800'
  const hover = onClick
    ? 'cursor-pointer transition-colors hover:bg-slate-100 dark:hover:bg-neutral-700 hover:shadow-md'
    : ''
  const ring = [
    selected && 'ring-2 ring-blue-500',
    dropActive && 'ring-2 ring-blue-500/60 bg-blue-50/50 dark:bg-blue-500/10',
  ].filter(Boolean).join(' ')
  const drag = { onDragEnter, onDragOver, onDragLeave, onDrop }

  if (!onClick) {
    return <div className={`${base} ${ring}`} {...drag}>{children}</div>
  }
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={label}
      onClick={(e) => onClick(e)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      className={`${base} ${hover} ${ring}`}
      {...drag}
    >
      {children}
    </div>
  )
}

export function CardBack({ className = 'w-16 rounded' }: { className?: string }) {
  return (
    <img
      src="/card-back.png"
      alt=""
      loading="lazy"
      className={`${className} aspect-[5/7] shrink-0 object-contain`}
    />
  )
}

export function CardArt({ artUrl, spriteUrl, className = 'w-16 rounded', fallback = 'blank' }: {
  artUrl?: string | null
  spriteUrl?: string | null
  className?: string
  fallback?: 'blank' | 'back'
}) {
  const [failed, setFailed] = useState(false)
  const src = artUrl ?? spriteUrl
  const box = `${className} aspect-[5/7] shrink-0`

  if (!src || failed) {
    if (fallback === 'back') return <CardBack className={className} />
    return <div className={`${box} bg-slate-100 dark:bg-neutral-700`} />
  }
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      // The sprite is a small pixel image; scaling it smoothly turns it to mush.
      style={artUrl ? undefined : { imageRendering: 'pixelated' }}
      className={`${box} object-contain`}
    />
  )
}
