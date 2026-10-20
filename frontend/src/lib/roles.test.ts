import { describe, expect, it } from 'vitest'

import { hasRole } from '@/lib/roles'

describe('hasRole', () => {
  it('lets higher roles do what lower roles can', () => {
    expect(hasRole('admin', 'manager')).toBe(true)
    expect(hasRole('manager', 'staff')).toBe(true)
    expect(hasRole('manager', 'manager')).toBe(true)
  })

  it('blocks lower roles and users without a role', () => {
    expect(hasRole('staff', 'manager')).toBe(false)
    expect(hasRole('manager', 'admin')).toBe(false)
    expect(hasRole(null, 'staff')).toBe(false)
  })
})
