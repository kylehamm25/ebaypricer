import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import {
  LayoutDashboard, ShoppingCart, Package, Boxes, History, LogOut, Settings, Sun, Moon,
} from 'lucide-react'
import { cn } from '../../lib/utils'
import { useAuth } from '../../lib/auth-context'
import { useTheme } from '../../lib/theme'

const links = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/sold', label: 'Sold Orders', icon: ShoppingCart },
  { to: '/active', label: 'Active Listings', icon: Package },
  { to: '/lots', label: 'Lots', icon: Boxes },
  { to: '/log', label: 'Price Log', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const location = useLocation()

  // Sidebar/Layout stay mounted across route changes, so remember the last
  // full path (including search/filter query params) visited under each
  // section - lets nav links return you to where you left off instead of
  // resetting filters every time you switch pages.
  const lastPaths = useRef<Record<string, string>>({})
  useEffect(() => {
    const match = links.find((l) => l.to === location.pathname)
    if (match) lastPaths.current[match.to] = location.pathname + location.search
  }, [location])

  const handleSignOut = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  return (
    <aside className="w-56 bg-black text-white flex flex-col h-screen fixed left-0 top-0">
      <div className="p-4 border-b border-neutral-800">
        <h1 className="text-lg font-bold">EbayPricer</h1>
        <p className="text-xs text-neutral-500">Dashboard</p>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={lastPaths.current[to] ?? to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-neutral-800 text-white font-medium'
                  : 'text-neutral-400 hover:bg-neutral-900 hover:text-white'
              )
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-2 border-t border-neutral-800">
        <button
          onClick={toggle}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm text-neutral-400 hover:bg-neutral-900 hover:text-white transition-colors"
          title="Toggle dark mode"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
        <button
          onClick={handleSignOut}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm text-neutral-400 hover:bg-neutral-900 hover:text-white transition-colors"
        >
          <LogOut size={18} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
