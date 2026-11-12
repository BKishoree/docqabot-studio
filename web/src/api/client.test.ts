import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

function respond(status: number, body: unknown, contentType = 'application/json') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(body === null ? null : typeof body === 'string' ? body : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': contentType },
      }),
    ),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('api client error mapping', () => {
  it('uses the envelope code and message', async () => {
    respond(413, {
      error: { code: 'file_too_large', message: 'The file is 31.2 MB. The limit is 20 MB.', details: { limit_bytes: 1 }, request_id: 'r1' },
    })
    const err = await api.uploadDocument(new File(['x'], 'a.txt')).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 413, code: 'file_too_large', message: 'The file is 31.2 MB. The limit is 20 MB.', requestId: 'r1' })
  })

  it('falls back to a readable error when the body is not an envelope', async () => {
    respond(502, '<html>Bad gateway</html>', 'text/html')
    const err = (await api.listDocuments().catch((e: unknown) => e)) as ApiError
    expect(err.code).toBe('internal_error')
    expect(err.message).toMatch(/went wrong/i)
  })

  it('maps a bare 401 to unauthorized', async () => {
    respond(401, { detail: 'Not authenticated' })
    const err = (await api.health().catch((e: unknown) => e)) as ApiError
    expect(err.code).toBe('unauthorized')
  })

  it('reports a network failure as network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const err = (await api.health().catch((e: unknown) => e)) as ApiError
    expect(err.status).toBe(0)
    expect(err.code).toBe('network_error')
  })

  it('returns undefined for 204', async () => {
    respond(204, null)
    await expect(api.deleteDocument(1)).resolves.toBeUndefined()
  })

  it('uses relative /api/v1 URLs only', async () => {
    respond(200, { items: [], total: 0 })
    await api.listConversations()
    const fetchMock = vi.mocked(fetch)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/conversations?limit=50&offset=0')
  })
})
