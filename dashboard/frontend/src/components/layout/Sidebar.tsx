import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, ShoppingCart, Package,
} from 'lucide-react'
import { cn } from '../../lib/utils'

const links = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/sold', label: 'Sold Orders', icon: ShoppingCart },
  { to: '/active', label: 'Active Listings', icon: Package },
]

export function Sidebar() {
  return (
    <aside className="w-56 bg-slate-900 text-white flex flex-col h-screen fixed left-0 top-0">
      <div className="p-4 border-b border-slate-700">
        <h1 className="text-lg font-bold">EbayPrice</h1>
        <p className="text-xs text-slate-400">Dashboard</p>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-slate-700 text-white font-medium'
                  : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              )
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
