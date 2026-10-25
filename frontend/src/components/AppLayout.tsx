import { LogOut, Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { BrandMark } from '@/components/BrandMark'
import { NAV } from '@/components/nav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { hasRole } from '@/lib/roles'
import { cn } from '@/lib/utils'

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { role } = useAuth()
  return (
    <nav className="flex flex-col gap-5 p-3" aria-label="Main">
      {NAV.map(({ section, items }) => {
        const visible = items.filter((i) => !i.minimum || hasRole(role, i.minimum))
        if (visible.length === 0) return null
        return (
          <div key={section || 'root'} className="grid gap-1">
            {section && <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{section}</p>}
            {visible.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                    isActive ? 'bg-accent font-medium text-brand shadow-[inset_2px_0_0_var(--brand)]' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                  )
                }
              >
                <Icon className="size-4" /> {label}
              </NavLink>
            ))}
          </div>
        )
      })}
    </nav>
  )
}

export function AppLayout() {
  const { user, role, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const navigate = useNavigate()

  // Go to a clean login page, so the next person to sign in starts at Home, not on this page.
  async function onSignOut() {
    navigate('/login', { replace: true })
    await signOut()
  }

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="sticky top-0 z-20 border-b bg-background">
        <div className="flex h-14 items-center justify-between gap-2 px-4">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Toggle menu" onClick={() => setMenuOpen((o) => !o)}>
              {menuOpen ? <X /> : <Menu />}
            </Button>
            <Link to="/" className="flex items-center gap-2 font-semibold">
              <BrandMark className="size-7" /> InvoiceFlow
            </Link>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="flex size-7 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold uppercase text-brand" aria-hidden>
              {user?.email?.[0] ?? '?'}
            </span>
            <span className="hidden text-muted-foreground sm:inline">{user?.email}</span>
            <Badge variant="secondary">{role ?? 'no role'}</Badge>
            <Button variant="ghost" size="sm" onClick={onSignOut}>
              <LogOut /> <span className="hidden sm:inline">Sign out</span>
            </Button>
          </div>
        </div>
      </header>
      <div className="flex">
        <aside className="sticky top-14 hidden h-[calc(100svh-3.5rem)] w-56 shrink-0 overflow-y-auto border-r bg-background md:block">
          <Sidebar />
        </aside>
        {menuOpen && (
          <aside className="fixed inset-x-0 top-14 bottom-0 z-10 overflow-y-auto bg-background md:hidden">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </aside>
        )}
        <main className="min-w-0 flex-1 p-4 sm:p-6">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
