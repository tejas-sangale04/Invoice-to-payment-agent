import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { NAV } from '@/components/nav'
import { ErrorState, LoadingState } from '@/components/States'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getMe } from '@/lib/api'
import { hasRole } from '@/lib/roles'

const BLURBS: Record<string, string> = {
  '/purchase-orders': 'Create and track what you ordered from suppliers.',
  '/deliveries/new': 'Record what actually arrived against a purchase order.',
  '/suppliers': 'Suppliers you buy from.',
  '/invoices/upload': 'Upload a supplier invoice PDF for checking.',
  '/invoices': 'Every invoice and where it is in the process.',
  '/approvals': 'Invoices waiting for a manager decision.',
  '/ledger': 'Invoices posted for payment.',
  '/dashboard': 'Volumes, decisions and money saved.',
  '/settings/rules': 'Price tolerance and approval limits.',
}

export function HomePage() {
  // The role used here comes from the backend, which verified the ID token and its claims.
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })

  if (me.isPending) return <LoadingState label="Checking your access…" />
  if (me.isError) return <ErrorState error={me.error} />

  const role = me.data.role
  const shortcuts = NAV.flatMap((s) => s.items).filter((i) => i.minimum && hasRole(role, i.minimum))

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Signed in as {me.data.email}
          {role ? ` with the ${role} role.` : '.'}
        </p>
      </div>
      {role ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shortcuts.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className="group">
              <Card className="h-full gap-2 transition-colors group-hover:border-ring">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Icon className="size-4 text-muted-foreground" /> {label}
                  </CardTitle>
                  <CardDescription>{BLURBS[to]}</CardDescription>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="text-sm">You don't have a role yet. Ask an admin to assign you one.</CardContent>
        </Card>
      )}
    </div>
  )
}
