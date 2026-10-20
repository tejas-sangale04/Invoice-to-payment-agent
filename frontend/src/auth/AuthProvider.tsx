import { onIdTokenChanged, signOut as fbSignOut, type User } from 'firebase/auth'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import type { Role } from '@/lib/api'
import { auth } from '@/lib/firebase'

interface AuthState {
  user: User | null
  role: Role | null
  loading: boolean
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [role, setRole] = useState<Role | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(
    () =>
      onIdTokenChanged(auth, async (next) => {
        setUser(next)
        if (next) {
          const { claims } = await next.getIdTokenResult()
          setRole((claims.role as Role | undefined) ?? null)
        } else {
          setRole(null)
        }
        setLoading(false)
      }),
    [],
  )

  return (
    <AuthContext.Provider value={{ user, role, loading, signOut: () => fbSignOut(auth) }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
