// In-memory mock of the /api/v1 contract (DESIGN section 4), served through `fetch`.
// Used by component tests and, optionally, by `VITE_MOCK_API=true npm run dev`.
// All demo content is synthetic.
import type {
  Citation,
  Config,
  ConversationDetail,
  ConversationSummary,
  DocumentItem,
  ErrorCode,
  Health,
  Message,
  OpenAIStatus,
} from '../api/types'

export interface MockState {
  mode: 'live' | 'demo'
  openai: OpenAIStatus
  database: 'ok' | 'unavailable'
  documents: DocumentItem[]
  conversations: ConversationDetail[]
  /** Next ask fails with this envelope (consumed once). */
  nextAskError: { status: number; code: ErrorCode; message: string } | null
  /** Next upload is rejected with this envelope (consumed once). */
  nextUploadError: { status: number; code: ErrorCode; message: string } | null
  /** Milliseconds every response waits; tests keep this at 0. */
  latency: number
  /** Number of list polls before a processing document turns ready. */
  pollsUntilReady: number
}

const CONFIG = (mode: 'live' | 'demo'): Config => ({
  version: '1.0.0',
  mode,
  max_upload_bytes: 20 * 1024 * 1024,
  allowed_extensions: ['.pdf', '.md', '.txt'],
  max_question_chars: 2000,
  embedding_model: 'text-embedding-3-small',
  chat_model: 'gpt-4o-mini',
  retrieval: { top_k: 5, min_similarity: 0.3 },
})

const iso = (offsetSec = 0) => new Date(Date.now() - offsetSec * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z')

export function seedDocuments(): DocumentItem[] {
  return [
    {
      id: 3,
      filename: 'travel-expenses-policy.md',
      status: 'ready',
      created_at: iso(3600),
      processed_at: iso(3590),
      size_bytes: 18_422,
      chunk_count: 6,
      error: null,
    },
    {
      id: 2,
      filename: 'employee-handbook-2026.pdf',
      status: 'ready',
      created_at: iso(7200),
      processed_at: iso(7180),
      size_bytes: 482_133,
      chunk_count: 14,
      error: null,
    },
    {
      id: 1,
      filename: 'supplier-contract-scan.pdf',
      status: 'failed',
      created_at: iso(9000),
      processed_at: iso(8990),
      size_bytes: 1_204_551,
      chunk_count: 0,
      error: {
        code: 'processing_failed',
        message: 'The document could not be processed. Remove it and upload it again.',
      },
    },
  ]
}

const VACATION_CITATIONS: Citation[] = [
  {
    rank: 1,
    document_id: 2,
    document_available: true,
    filename: 'employee-handbook-2026.pdf',
    chunk_index: 3,
    similarity: 0.6214,
    text:
      'Section 4.2 Paid vacation\n\nFull-time employees accrue 20 days of paid vacation per calendar year, ' +
      'credited monthly. Part-time employees accrue vacation in proportion to their contracted hours. ' +
      'Up to 5 unused days may be carried over to the next calendar year.',
  },
  {
    rank: 2,
    document_id: null,
    document_available: false,
    filename: 'leave-policy-2025.md',
    chunk_index: null,
    similarity: 0.4102,
    text: 'Vacation requests of more than 10 consecutive days must be submitted at least four weeks in advance.',
  },
]

export function seedConversations(): ConversationDetail[] {
  const user: Message = {
    id: 1,
    role: 'user',
    content: 'How many vacation days do full-time employees get?',
    created_at: iso(1800),
    grounded: null,
    citations: [],
  }
  const assistant: Message = {
    id: 2,
    role: 'assistant',
    content:
      'Full-time employees accrue 20 days of paid vacation per calendar year, and up to 5 unused days can be ' +
      'carried over (employee-handbook-2026.pdf).',
    created_at: iso(1795),
    grounded: true,
    citations: VACATION_CITATIONS,
  }
  return [
    {
      id: '5b0a3c1e-7c59-4d0e-9a55-0c9d5f3a2b11',
      title: 'How many vacation days do full-time employees get?',
      created_at: iso(1800),
      updated_at: iso(1795),
      message_count: 2,
      messages: [user, assistant],
    },
  ]
}

export function createMockState(overrides: Partial<MockState> = {}): MockState {
  return {
    mode: 'demo',
    openai: 'ok',
    database: 'ok',
    documents: seedDocuments(),
    conversations: seedConversations(),
    nextAskError: null,
    nextUploadError: null,
    latency: 0,
    pollsUntilReady: 1,
    ...overrides,
  }
}

const NOT_GROUNDED =
  "I couldn't find relevant information in the uploaded documents to answer your question."

function envelope(status: number, code: ErrorCode, message: string, details: Record<string, unknown> | null = null) {
  return new Response(JSON.stringify({ error: { code, message, details, request_id: 'mock0000' } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function ok(body: unknown, status = 200) {
  if (status === 204) return new Response(null, { status })
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function summary(c: ConversationDetail): ConversationSummary {
  return {
    id: c.id,
    title: c.title,
    created_at: c.created_at,
    updated_at: c.updated_at,
    message_count: c.messages.length,
  }
}

let idCounter = 1000
const nextId = () => ++idCounter

function uuid(): string {
  const hex = () => Math.floor(Math.random() * 16).toString(16)
  const s = (n: number) => Array.from({ length: n }, hex).join('')
  return `${s(8)}-${s(4)}-4${s(3)}-a${s(3)}-${s(12)}`
}

/** Build a fetch implementation backed by `state`. */
export function createMockFetch(state: MockState): typeof fetch {
  const processingPolls = new Map<number, number>()

  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://mock')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname
    if (state.latency) await new Promise((r) => setTimeout(r, state.latency))

    if (path === '/api/v1/health') {
      const health: Health = {
        status: state.database === 'ok' && state.openai === 'ok' ? 'ok' : 'degraded',
        version: '1.0.0',
        mode: state.mode,
        auth_enabled: false,
        components: {
          database: {
            status: state.database,
            detail: state.database === 'ok' ? null : 'The database cannot be reached.',
          },
          openai: {
            status: state.openai,
            detail:
              state.openai === 'ok'
                ? null
                : state.openai === 'not_configured'
                  ? 'OPENAI_API_KEY is not set.'
                  : state.openai === 'invalid_key'
                    ? 'OpenAI rejected the API key.'
                    : 'OpenAI could not be reached.',
            checked_at: iso(),
          },
        },
      }
      return ok(health)
    }
    if (path === '/api/v1/config') return ok(CONFIG(state.mode))

    if (state.database === 'unavailable') {
      return envelope(503, 'database_unavailable', 'The database is unavailable. Try again in a moment.')
    }

    // ---- Documents
    if (path === '/api/v1/documents' && method === 'GET') {
      for (const doc of state.documents) {
        if (doc.status !== 'processing') continue
        const n = (processingPolls.get(doc.id) ?? 0) + 1
        processingPolls.set(doc.id, n)
        if (n > state.pollsUntilReady) {
          doc.status = 'ready'
          doc.chunk_count = 3
          doc.processed_at = iso()
        }
      }
      return ok({ items: state.documents, total: state.documents.length })
    }
    if (path === '/api/v1/documents' && method === 'POST') {
      if (state.openai === 'not_configured') {
        return envelope(503, 'openai_not_configured', 'OpenAI is not configured. Add OPENAI_API_KEY or use demo mode.')
      }
      if (state.nextUploadError) {
        const e = state.nextUploadError
        state.nextUploadError = null
        return envelope(e.status, e.code, e.message)
      }
      const file = (init?.body as FormData | undefined)?.get('file')
      const name = file instanceof File ? file.name : 'upload.txt'
      const size = file instanceof File ? file.size : 0
      const ext = name.slice(name.lastIndexOf('.')).toLowerCase()
      if (!['.pdf', '.md', '.txt'].includes(ext)) {
        return envelope(415, 'unsupported_file_type', `"${name}" is not a supported file type. Use PDF, Markdown or text.`)
      }
      if (size === 0) return envelope(400, 'empty_file', `"${name}" is empty.`)
      if (size > CONFIG(state.mode).max_upload_bytes) {
        return envelope(413, 'file_too_large', `The file is too large. The limit is 20 MB.`)
      }
      const doc: DocumentItem = {
        id: nextId(),
        filename: name,
        status: 'processing',
        created_at: iso(),
        processed_at: null,
        size_bytes: size,
        chunk_count: 0,
        error: null,
      }
      state.documents.unshift(doc)
      return ok(doc, 202)
    }
    const docMatch = path.match(/^\/api\/v1\/documents\/(\d+)$/)
    if (docMatch) {
      const id = Number(docMatch[1])
      const idx = state.documents.findIndex((d) => d.id === id)
      if (idx < 0) return envelope(404, 'not_found', 'Document not found.')
      if (method === 'DELETE') {
        const [removed] = state.documents.splice(idx, 1)
        for (const c of state.conversations)
          for (const m of c.messages)
            for (const cit of m.citations)
              if (cit.document_id === removed?.id) {
                cit.document_id = null
                cit.document_available = false
              }
        return ok(null, 204)
      }
      return ok(state.documents[idx])
    }

    // ---- Conversations
    if (path === '/api/v1/conversations' && method === 'GET') {
      const items = [...state.conversations]
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .map(summary)
      return ok({ items, total: items.length })
    }
    if (path === '/api/v1/conversations' && method === 'POST') {
      const body = init?.body ? (JSON.parse(String(init.body)) as { title?: string }) : {}
      const now = iso()
      const conv: ConversationDetail = {
        id: uuid(),
        title: body.title ?? 'New conversation',
        created_at: now,
        updated_at: now,
        message_count: 0,
        messages: [],
      }
      state.conversations.unshift(conv)
      return ok(summary(conv), 201)
    }
    const convMatch = path.match(/^\/api\/v1\/conversations\/([^/]+)(\/messages)?$/)
    if (convMatch) {
      const id = decodeURIComponent(convMatch[1]!)
      const conv = state.conversations.find((c) => c.id === id)
      if (!conv) return envelope(404, 'not_found', 'Conversation not found.')
      if (convMatch[2] && method === 'POST') {
        const { question } = JSON.parse(String(init?.body ?? '{}')) as { question?: string }
        const q = (question ?? '').trim()
        if (!q || q.length > 2000) {
          return envelope(422, 'validation_error', 'The question must be between 1 and 2000 characters.', {
            fields: [{ field: 'question', message: 'Length 1..2000' }],
          })
        }
        if (state.nextAskError) {
          const e = state.nextAskError
          state.nextAskError = null
          return envelope(e.status, e.code, e.message)
        }
        if (state.openai === 'not_configured') {
          return envelope(503, 'openai_not_configured', 'OpenAI is not configured. Add OPENAI_API_KEY or use demo mode.')
        }
        if (!state.documents.some((d) => d.status === 'ready')) {
          return envelope(409, 'no_ready_documents', 'Upload a document and wait until it is ready before asking.')
        }
        const grounded = !/weather|football|recipe/i.test(q)
        const now = iso()
        const user: Message = { id: nextId(), role: 'user', content: q, created_at: now, grounded: null, citations: [] }
        const assistant: Message = {
          id: nextId(),
          role: 'assistant',
          content: grounded
            ? `[Simulated answer] Based on employee-handbook-2026.pdf: Full-time employees accrue 20 days of paid vacation per calendar year.`
            : NOT_GROUNDED,
          created_at: now,
          grounded,
          citations: grounded ? [{ ...VACATION_CITATIONS[0]! }] : [],
        }
        conv.messages.push(user, assistant)
        if (conv.title === 'New conversation') conv.title = q.slice(0, 60)
        conv.updated_at = now
        conv.message_count = conv.messages.length
        return ok({ conversation: summary(conv), user_message: user, assistant_message: assistant }, 201)
      }
      if (method === 'PATCH') {
        const { title } = JSON.parse(String(init?.body ?? '{}')) as { title?: string }
        const t = (title ?? '').trim()
        if (!t || t.length > 120) {
          return envelope(422, 'validation_error', 'The title must be between 1 and 120 characters.')
        }
        conv.title = t
        conv.updated_at = iso()
        return ok(summary(conv))
      }
      if (method === 'DELETE') {
        state.conversations = state.conversations.filter((c) => c.id !== id)
        return ok(null, 204)
      }
      return ok({ ...summary(conv), messages: conv.messages })
    }
    return envelope(404, 'not_found', 'This API path does not exist.')
  }
}
