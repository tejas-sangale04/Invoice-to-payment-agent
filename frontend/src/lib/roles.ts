import type { Role } from '@/lib/api'

// Mirrors backend/app/models/user.py. For showing and hiding UI only; the backend enforces access.
const RANK: Record<Role, number> = { staff: 1, manager: 2, admin: 3 }

export function hasRole(role: Role | null | undefined, minimum: Role): boolean {
  return role != null && RANK[role] >= RANK[minimum]
}
