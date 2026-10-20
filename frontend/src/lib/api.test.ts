import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/firebase', () => ({
  auth: { currentUser: { getIdToken: () => Promise.resolve('tok-123') } },
}))

import { ApiError, apiFetch } from '@/lib/api'

afterEach(() => vi.unstubAllGlobals())

describe('apiFetch', () => {
  it('sends the Firebase ID token as a bearer header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiFetch('/me')).resolves.toEqual({ ok: true })
    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer tok-123')
  })

  it('turns the backend error shape into an ApiError', async () => {
    const body = { error: { code: 'forbidden', message: 'Requires the manager role' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 403 })))

    const err = await apiFetch('/ledger').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 403, code: 'forbidden', message: 'Requires the manager role' })
  })
})
