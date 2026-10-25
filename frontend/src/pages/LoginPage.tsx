import { signInWithEmailAndPassword } from 'firebase/auth'
import { CheckCircle2, Eye, EyeOff, Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { BrandMark } from '@/components/BrandMark'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { auth } from '@/lib/firebase'

const POINTS = [
  'Reads each invoice and checks it against the purchase order and delivery',
  'Approves the clean ones and sends the rest to a manager',
  'Keeps a full audit trail of every decision',
]

// Only the local emulator has these users, so the shortcuts never show against real Firebase.
const DEMO_USERS = import.meta.env.VITE_USE_AUTH_EMULATOR === 'true' ? ['staff', 'manager', 'admin'] : []

export function LoginPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const from = (location.state as { from?: string } | null)?.from ?? '/'
  if (user) return <Navigate to={from} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await signInWithEmailAndPassword(auth, email, password)
      navigate(from, { replace: true })
    } catch {
      setError('Email or password is incorrect.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-svh lg:grid-cols-2">
      <section className="hidden flex-col justify-between bg-brand p-12 text-primary-foreground lg:flex">
        <div className="flex items-center gap-3 text-lg font-semibold">
          <BrandMark className="bg-primary-foreground/15" /> InvoiceFlow
        </div>
        <div className="max-w-md">
          <h2 className="text-3xl font-semibold leading-tight">From supplier invoice to payment, with an agent doing the checking.</h2>
          <ul className="mt-8 grid gap-4">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-3 text-sm text-primary-foreground/90">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-primary-foreground/70">Purchase orders, deliveries and invoices in one place.</p>
      </section>

      <section className="flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <BrandMark /> <span className="text-lg font-semibold">InvoiceFlow</span>
          </div>
          <h1 className="text-2xl font-semibold">Welcome back</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to manage purchase orders, deliveries and invoices.</p>

          <form onSubmit={onSubmit} className="mt-8 grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  className="pr-10"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>
            {error && (
              <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting && <Loader2 className="animate-spin" />}
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          {DEMO_USERS.length > 0 && (
            <div className="mt-8 border-t pt-4">
              <p className="mb-2 text-xs text-muted-foreground">Local demo accounts (fills the form)</p>
              <div className="flex gap-2">
                {DEMO_USERS.map((u) => (
                  <Button
                    key={u}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setEmail(`${u}@invoiceflow.test`)
                      setPassword('password123')
                    }}
                  >
                    {u}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
