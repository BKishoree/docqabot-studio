// Types written from docs/DESIGN.md section 4 (API contract v1.2).

export type ErrorCode =
  | 'empty_file'
  | 'invalid_filename'
  | 'invalid_encoding'
  | 'upload_rejected'
  | 'unauthorized'
  | 'not_found'
  | 'no_ready_documents'
  | 'file_too_large'
  | 'unsupported_file_type'
  | 'validation_error'
  | 'no_extractable_text'
  | 'unreadable_file'
  | 'openai_auth_failed'
  | 'openai_unreachable'
  | 'openai_error'
  | 'openai_rate_limited'
  | 'openai_not_configured'
  | 'database_unavailable'
  | 'internal_error'
  // Client-side only: the request never got a usable answer.
  | 'network_error'

export interface ErrorBody {
  code: ErrorCode
  message: string
  details: Record<string, unknown> | null
  request_id: string
}

export interface ErrorEnvelope {
  error: ErrorBody
}

export type Mode = 'live' | 'demo'
export type OpenAIStatus = 'ok' | 'not_configured' | 'invalid_key' | 'unreachable' | 'error'

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  mode: Mode
  auth_enabled: boolean
  components: {
    database: { status: 'ok' | 'unavailable'; detail: string | null }
    openai: { status: OpenAIStatus; detail: string | null; checked_at: string }
  }
}

export interface Config {
  version: string
  mode: Mode
  max_upload_bytes: number
  allowed_extensions: string[]
  max_question_chars: number
  embedding_model: string
  chat_model: string
  retrieval: { top_k: number; min_similarity: number }
}

export type DocumentStatus = 'processing' | 'ready' | 'failed'
export type DocumentErrorCode = 'processing_failed' | 'openai_auth' | 'openai_unreachable' | 'interrupted'

export interface DocumentItem {
  id: number
  filename: string
  status: DocumentStatus
  created_at: string
  processed_at: string | null
  size_bytes: number | null
  chunk_count: number
  error: { code: DocumentErrorCode; message: string } | null
}

export interface ListResponse<T> {
  items: T[]
  total: number
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Citation {
  rank: number
  document_id: number | null
  document_available: boolean
  filename: string
  chunk_index: number | null
  similarity: number
  text: string
}

export interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  grounded: boolean | null
  citations: Citation[]
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[]
}

export interface AskResponse {
  conversation: ConversationSummary
  user_message: Message
  assistant_message: Message
}
