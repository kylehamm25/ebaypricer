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

/** The tile shell every grid uses, so cards on different pages are the same object
 *  with different contents: art full-bleed on top, details, then actions. */
export function GridShell({ selected, onClick, label, children, dropActive, onDragEnter, onDragOver, onDragLeave, onDrop }: {
  selected?: boolean
  /** Makes the WHOLE tile the click target. Without it the tile is inert and gets
   *  no hover treatment - a card that lights up under the cursor but only responds
   *  on one part of itself is worse than one that never lights up at all. Receives
   *  the click event so callers can read modifiers (the inventory grid uses
   *  shift-click for range select); keyboard activation calls it with no event.
   *  Zero-arg handlers still typecheck - an extra argument is simply ignored. */
  onClick?: (e?: React.MouseEvent) => void
  /** Accessible name for the tile when it is clickable. */
  label?: string
  children: React.ReactNode
  /** Highlights the tile while a drag-and-drop is over it - a second, independent
   *  ring from `selected`, since a page that accepts a drop has no reason to also
   *  select the tile it landed on. Plain pass-through: this component holds no
   *  drag state or upload logic of its own, so any page can wire a drop target
   *  onto the same shell every other tile already uses. */
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

/** The Pokemon card back, for when there is no art to show.
 *
 *  Served from our own public/ rather than hotlinked. images.pokemontcg.io returns
 *  this exact PNG as the BODY of its 404s - which is why a card from a set the CDN
 *  has not published yet (me3, at the time of writing) appears as a card back
 *  rather than a broken image. Depending on an error page staying an image is not
 *  a fallback, so the file is vendored and referenced directly.
 */
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

/** Card art with a sprite fallback, sized by the caller.
 *
 *  Real art distinguishes printings; the species sprite cannot - every Charizard
 *  shares one. The empty box keeps rows and tiles aligned when there is neither. */
export function CardArt({ artUrl, spriteUrl, className = 'w-16 rounded', fallback = 'blank' }: {
  artUrl?: string | null
  spriteUrl?: string | null
  className?: string
  /** What to show when there is no image at all. 'blank' is an empty box that
   *  simply holds the space; 'back' shows the card back, which reads as "a card
   *  we can't picture" rather than as a gap. Per page, because a wall of card
   *  backs says something different from one of them in a row. */
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
