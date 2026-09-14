import { useEffect, useState } from 'react'
import { useAuth } from './auth-context'

export type View = 'table' | 'grid'

/** One grid's column counts and gutter. Defined once so a change to card size on
 *  one page doesn't leave the others behind. */
export const GRID_CLASS = 'grid gap-6 grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8'

/** Remembers which layout a page was last shown in.
 *
 *  Per user rather than per browser, so two accounts on one machine don't inherit
 *  each other's - the same reasoning as the Valuation page's saved draft. Per page
 *  too: a grid suits a wall of card art and a table suits scanning numbers, and
 *  which you want is not the same answer on every screen.
 *
 *  Table is always the fallback: it is the denser view and the one whose column
 *  headers sort. */
export function useViewPreference(page: string): [View, (v: View) => void] {
  const { user } = useAuth()
  const key = `ebayprice.${page}.view.v1.${user?.id ?? 'anon'}`
  const [view, setView] = useState<View>('table')

  useEffect(() => {
    try {
      setView(localStorage.getItem(key) === 'grid' ? 'grid' : 'table')
    } catch {
      // Storage blocked (private mode) or unreadable. The page works without it.
      setView('table')
    }
  }, [key])

  const choose = (next: View) => {
    setView(next)
    try {
      localStorage.setItem(key, next)
    } catch {
      // The choice still applies for this visit; it just won't be remembered.
    }
  }

  return [view, choose]
}
