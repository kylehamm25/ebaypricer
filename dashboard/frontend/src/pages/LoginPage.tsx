import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, LogIn, UserPlus, Sun, Moon } from 'lucide-react'
import { useAuth } from '../lib/auth-context'
import { useTheme } from '../lib/theme'

export function LoginPage() {
  const { signIn, signUp } = useAuth()
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setInfo(null)
    setPending(true)
    try {
      if (mode === 'login') {
        await signIn(email, password)
        navigate('/dashboard', { replace: true })
      } else {
        await signUp(email, password)
        setInfo('Account created. Check your email to confirm, then sign in.')
        setMode('login')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="relative min-h-screen bg-slate-50 dark:bg-neutral-900 flex items-center justify-center">
      <button
        onClick={toggle}
        className="absolute top-4 right-4 p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-200 dark:text-neutral-400 dark:hover:text-neutral-200 dark:hover:bg-neutral-700 transition-colors"
        title="Toggle dark mode"
      >
        {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
      </button>
      <div className="w-full max-w-sm bg-white dark:bg-neutral-800 rounded-xl p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-neutral-100">EbayPricer</h1>
          <p className="text-sm text-slate-500 dark:text-neutral-400 mt-1">
            {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
          </p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-neutral-300 mb-1" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="you@example.com"
              autoComplete="email"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-neutral-300 mb-1" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {info && <p className="text-sm text-emerald-600 dark:text-emerald-400">{info}</p>}

          <button
            type="submit"
            disabled={pending}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {pending ? <Loader2 size={16} className="animate-spin" /> : mode === 'login' ? <LogIn size={16} /> : <UserPlus size={16} />}
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="text-center text-sm text-slate-500 dark:text-neutral-400 mt-6">
          {mode === 'login' ? (
            <>
              No account?{' '}
              <button className="text-blue-600 dark:text-blue-400 hover:underline font-medium" onClick={() => { setMode('register'); setError(null); setInfo(null) }}>
                Register
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button className="text-blue-600 dark:text-blue-400 hover:underline font-medium" onClick={() => { setMode('login'); setError(null); setInfo(null) }}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
