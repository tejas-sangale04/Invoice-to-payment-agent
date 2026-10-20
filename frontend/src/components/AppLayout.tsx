import { LogOut } from 'lucide-react'
import { Link, Outlet } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function AppLayout() {
  const { user, role, signOut } = useAuth()

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="font-semibold">
            InvoiceFlow
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-muted-foreground sm:inline">{user?.email}</span>
            <Badge variant="secondary">{role ?? 'no role'}</Badge>
            <Button variant="ghost" size="sm" onClick={signOut}>
              <LogOut /> Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  )
}
