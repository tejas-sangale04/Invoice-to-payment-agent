import { useQueryClient } from '@tanstack/react-query'
import { onIdTokenChanged, signOut as fbSignOut, type User } from 'firebase/auth'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

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
  const queryClient = useQueryClient()
  const lastUid = useRef<string | null>(null)

  useEffect(
    () =>
      onIdTokenChanged(auth, async (next) => {
        // A different account (or none) must never see the previous user's cached data.
        const uid = next?.uid ?? null
        if (uid !== lastUid.current) queryClient.clear()
        lastUid.current = uid
        setUser(next)
        if (next) {
          const { claims } = await next.getIdTokenResult()
          setRole((claims.role as Role | undefined) ?? null)
        } else {
          setRole(null)
        }
        setLoading(false)
      }),
    [queryClient],
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
