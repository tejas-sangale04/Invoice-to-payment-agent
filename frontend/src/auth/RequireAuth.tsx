import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import type { Role } from '@/lib/api'
import { hasRole } from '@/lib/roles'

export function RequireAuth({ children, minimum }: { children: ReactNode; minimum?: Role }) {
  const { user, role, loading } = useAuth()
  const location = useLocation()

  if (loading) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (minimum && !hasRole(role, minimum)) {
    return <p className="p-8 text-sm">You don't have access to this page.</p>
  }
  return <>{children}</>
}
