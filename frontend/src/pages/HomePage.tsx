import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getMe, type Role } from '@/lib/api'

const CAPABILITIES: Record<Role, string[]> = {
  staff: ['Create purchase orders', 'Record deliveries', 'Upload invoices', 'View invoices'],
  manager: ['Everything staff can do', 'Approve or reject invoices', 'View the ledger and dashboard'],
  admin: ['Everything managers can do', 'Manage users, suppliers and business rules'],
}

export function HomePage() {
  // The role shown here comes from the backend, which verified the ID token and its claims.
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Welcome</CardTitle>
        <CardDescription>Your account as verified by the InvoiceFlow API.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        {me.isPending && <p className="text-muted-foreground">Checking your access…</p>}
        {me.isError && (
          <p role="alert" className="text-destructive">
            Couldn't reach the API: {me.error.message}
          </p>
        )}
        {me.data && (
          <>
            <div className="flex items-center gap-2">
              <span>{me.data.email}</span>
              {me.data.role ? (
                <Badge variant="success">{me.data.role}</Badge>
              ) : (
                <Badge variant="warning">no role</Badge>
              )}
            </div>
            {me.data.role ? (
              <ul className="list-disc pl-5 text-muted-foreground">
                {CAPABILITIES[me.data.role].map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">Ask an admin to assign you a role before you can use InvoiceFlow.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
