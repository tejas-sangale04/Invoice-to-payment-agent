import { auth } from '@/lib/firebase'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Role = 'staff' | 'manager' | 'admin'

export interface Me {
  uid: string
  email: string | null
  role: Role | null
}

/** Matches the backend's error shape: {"error": {"code", "message", "details"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** Fetch from the backend with the current user's Firebase ID token attached. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await auth.currentUser?.getIdToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const res = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error?.code ?? 'error', body?.error?.message ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export const getMe = () => apiFetch<Me>('/me')
