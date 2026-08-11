import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue>({ theme: 'light', toggle: () => {} })

function getInitialTheme(): Theme {
  const saved = localStorage.getItem('theme')
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    document.documentElement.style.colorScheme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}

/** Theme-aware Recharts <Tooltip cursor={...}> styles - Recharts' own default
 * cursor colors are light-mode only and barely visible (bar) or wrong (line)
 * against a dark card background. */
export function useChartCursor() {
  const { theme } = useTheme()
  const dark = theme === 'dark'
  return {
    bar: { fill: dark ? 'rgba(255,255,255,0.06)' : 'rgba(15,23,42,0.04)' },
    line: { stroke: dark ? '#525252' : '#cbd5e1', strokeWidth: 1 },
  }
}
