// TESTER: FE-API — the typed client maps every failure to ApiError with the server's code/message (DESIGN 6.3).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, toApiError } from '../src/api/client'

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

const envelope = (code: string, message: string, details: Record<string, unknown> | null = null) => ({
  error: { code, message, details, request_id: 'req-123' },
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('toApiError', () => {
  const codes: Array<[number, string]> = [
    [400, 'empty_file'],
    [400, 'invalid_filename'],
    [400, 'invalid_encoding'],
    [401, 'unauthorized'],
    [404, 'not_found'],
    [409, 'no_ready_documents'],
    [413, 'file_too_large'],
    [415, 'unsupported_file_type'],
    [422, 'validation_error'],
    [422, 'no_extractable_text'],
    [422, 'unreadable_file'],
    [502, 'openai_auth_failed'],
    [502, 'openai_unreachable'],
    [502, 'openai_error'],
    [503, 'openai_rate_limited'],
    [503, 'openai_not_configured'],
    [503, 'database_unavailable'],
    [500, 'internal_error'],
  ]
  it.each(codes)('keeps status %i and code %s from the envelope', async (status, code) => {
    const err = await toApiError(jsonResponse(status, envelope(code, `msg for ${code}`, { a: 1 })))
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(status)
    expect(err.code).toBe(code)
    expect(err.message).toBe(`msg for ${code}`)
    expect(err.details).toEqual({ a: 1 })
    expect(err.requestId).toBe('req-123')
  })

  it('falls back to a readable message when the body is not an envelope (e.g. proxy HTML)', async () => {
    const err = await toApiError(new Response('<html>Bad gateway</html>', { status: 502 }))
    expect(err.status).toBe(502)
    expect(err.code).toBe('internal_error')
    expect(err.message).not.toMatch(/<html>/)
    expect(err.message.length).toBeGreaterThan(10)
  })

  it('maps a bare 401 (browser auth prompt case) to unauthorized', async () => {
    const err = await toApiError(new Response('', { status: 401 }))
    expect(err.code).toBe('unauthorized')
  })

  it('ignores a malformed envelope', async () => {
    const err = await toApiError(jsonResponse(503, { error: { code: 42 } }))
    expect(err.code).toBe('database_unavailable')
  })
})

describe('api requests', () => {
  it('uses relative same-origin /api/v1 URLs only', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse(200, { items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)
    await api.listDocuments()
    await api.listConversations(10, 20)
    await api.getConversation('a/b')
    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls).toEqual(['/api/v1/documents', '/api/v1/conversations?limit=10&offset=20', '/api/v1/conversations/a%2Fb'])
    for (const u of urls) expect(u.startsWith('/api/v1/')).toBe(true)
  })

  it('sends the question as JSON and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.ask('c1', 'What is it?')).resolves.toEqual({ ok: true })
    const [, init] = fetchMock.mock.calls[0]!
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ question: 'What is it?' })
  })

  it('uploads one multipart field named file', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    await api.uploadDocument(new File(['hello'], 'notes.txt', { type: 'text/plain' }))
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/documents')
    const form = init.body as FormData
    expect([...form.keys()]).toEqual(['file'])
    expect((form.get('file') as File).name).toBe('notes.txt')
  })

  it('returns undefined for 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(api.deleteDocument(3)).resolves.toBeUndefined()
  })

  it('throws ApiError with the envelope for a failed call', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(409, envelope('no_ready_documents', 'Upload first.'))))
    await expect(api.ask('c1', 'q')).rejects.toMatchObject({ code: 'no_ready_documents', status: 409, message: 'Upload first.' })
  })

  it('turns a network failure into a readable ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await api.health().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
    expect(err.message).not.toMatch(/Failed to fetch/)
  })
})
