import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Layout } from './components/layout/Layout'
import { AuthProvider } from './lib/auth'
import { useAuth } from './lib/auth-context'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { SoldOrdersPage } from './pages/SoldOrdersPage'
import { ActiveListingsPage } from './pages/ActiveListingsPage'
import { ListingDetailPage } from './pages/ListingDetailPage'
import { SettingsPage } from './pages/SettingsPage'

const queryClient = new QueryClient()

function Protected({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-neutral-900">
        <Loader2 size={32} className="text-blue-500 animate-spin" />
      </div>
    )
  }
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AppRoutes() {
  const { session } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={session ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
      <Route element={
        <Protected>
          <Layout />
        </Protected>
      }>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/sold" element={<SoldOrdersPage />} />
        <Route path="/active" element={<ActiveListingsPage />} />
        <Route path="/active/:itemId" element={<ListingDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
