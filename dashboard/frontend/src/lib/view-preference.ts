import { useEffect, useState } from 'react'
import { useAuth } from './auth-context'

export type View = 'table' | 'grid'

export const GRID_CLASS = 'grid gap-6 grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8'

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
