// The one typed client for /api/v1 (DESIGN 6.3). Relative URLs, same origin.
import type {
  AskResponse,
  Config,
  ConversationDetail,
  ConversationSummary,
  DocumentItem,
  ErrorBody,
  ErrorCode,
  Health,
  ListResponse,
} from './types'

const BASE = '/api/v1'

/** Error raised for every failed call. UI branches on `code`, shows `message`. */
export class ApiError extends Error {
  readonly code: ErrorCode
  readonly status: number
  readonly details: Record<string, unknown> | null
  readonly requestId: string | null

  constructor(status: number, body: Pick<ErrorBody, 'code' | 'message'> & Partial<ErrorBody>) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details ?? null
    this.requestId = body.request_id ?? null
  }
}

const FALLBACK_MESSAGES: Partial<Record<number, { code: ErrorCode; message: string }>> = {
  401: { code: 'unauthorized', message: 'Sign-in is required. Reload the page to enter the workspace password.' },
  404: { code: 'not_found', message: 'This item no longer exists.' },
  413: { code: 'file_too_large', message: 'The file is larger than the upload limit.' },
  503: { code: 'database_unavailable', message: 'The service is temporarily unavailable.' },
}

function isEnvelope(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const err = (value as { error: unknown }).error
  return (
    typeof err === 'object' &&
    err !== null &&
    typeof (err as ErrorBody).code === 'string' &&
    typeof (err as ErrorBody).message === 'string'
  )
}

/** Turn any non-2xx response into an ApiError, preferring the server envelope. */
export async function toApiError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null)
  if (isEnvelope(body)) return new ApiError(response.status, body.error)
  const fallback = FALLBACK_MESSAGES[response.status] ?? {
    code: 'internal_error' as const,
    message: 'Something went wrong on the server. Try again in a moment.',
  }
  return new ApiError(response.status, fallback)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      credentials: 'same-origin',
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, {
      code: 'network_error',
      message: 'The app server cannot be reached. Check that it is running, then try again.',
    })
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  health: (refresh = false) => request<Health>(`/health${refresh ? '?refresh=true' : ''}`),
  config: () => request<Config>('/config'),

  listDocuments: () => request<ListResponse<DocumentItem>>('/documents'),
  getDocument: (id: number) => request<DocumentItem>(`/documents/${id}`),
  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<DocumentItem>('/documents', { method: 'POST', body: form })
  },
  deleteDocument: (id: number) => request<void>(`/documents/${id}`, { method: 'DELETE' }),

  listConversations: (limit = 50, offset = 0) =>
    request<ListResponse<ConversationSummary>>(`/conversations?limit=${limit}&offset=${offset}`),
  createConversation: (title?: string) =>
    request<ConversationSummary>('/conversations', json('POST', title ? { title } : {})),
  getConversation: (id: string) => request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),
  renameConversation: (id: string, title: string) =>
    request<ConversationSummary>(`/conversations/${encodeURIComponent(id)}`, json('PATCH', { title })),
  deleteConversation: (id: string) =>
    request<void>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  ask: (id: string, question: string) =>
    request<AskResponse>(`/conversations/${encodeURIComponent(id)}/messages`, json('POST', { question })),
}

export type Api = typeof api
