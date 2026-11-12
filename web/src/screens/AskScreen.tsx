import { AlertCircle, FileSearch, Pencil, SearchX, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useAsk, useConfig, useConversation, useDeleteConversation, useRenameConversation } from '../api/queries'
import type { Message } from '../api/types'
import { Composer, type ComposerHandle } from '../components/Composer'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Sources } from '../components/Sources'
import { announce } from '../lib/announce'
import { formatDateTime, plural } from '../lib/format'
import { useSystem } from '../lib/system'

interface PendingTurn {
  question: string
  status: 'sending' | 'failed'
  error?: ApiError
  conversationId?: string
}

/** `/` (new conversation) and `/c/:conversationId` (thread). */
export function AskScreen() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const sys = useSystem()
  const config = useConfig()
  const conversation = useConversation(conversationId)
  const ask = useAsk()
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<PendingTurn | null>(null)
  const composer = useRef<ComposerHandle>(null)
  const endRef = useRef<HTMLDivElement>(null)

  // Reset local state when switching conversations (adjusted during render).
  const [shownId, setShownId] = useState(conversationId)
  if (shownId !== conversationId) {
    setShownId(conversationId)
    // Coming from "/" right after the first answer: nothing pending to keep.
    setPending(null)
    setDraft('')
  }
  useEffect(() => {
    composer.current?.focus()
  }, [conversationId])

  const messages = conversation.data?.messages ?? []
  useEffect(() => {
    if (messages.length || pending) endRef.current?.scrollIntoView({ block: 'end', behavior: 'auto' })
  }, [messages.length, pending])

  const send = (question: string, reuseId?: string) => {
    const q = question.trim()
    setPending({ question: q, status: 'sending' })
    setDraft('')
    ask.mutate(
      { conversationId: conversationId ?? reuseId, question: q },
      {
        onSuccess: (res) => {
          setPending(null)
          announce(
            res.assistant_message.grounded
              ? `Answer ready with ${plural(res.assistant_message.citations.length, 'source')}.`
              : 'Answer ready. Nothing relevant was found in your documents.',
          )
          if (!conversationId) navigate(`/c/${res.conversation.id}`)
          requestAnimationFrame(() => composer.current?.focus())
        },
        onError: (error) => {
          const err =
            error instanceof ApiError
              ? error
              : new ApiError(0, { code: 'internal_error', message: 'Something went wrong. Try again.' })
          const createdId = (error as { conversationId?: string }).conversationId
          setPending({ question: q, status: 'failed', error: err, conversationId: createdId })
          setDraft(q)
          announce(`The question was not answered. ${err.message}`, 'assertive')
          requestAnimationFrame(() => composer.current?.focus())
        },
      },
    )
  }

  const maxChars = config.data?.max_question_chars ?? 2000
  const sending = pending?.status === 'sending'

  // ---- Conversation-level states
  if (conversationId && conversation.isError) {
    const notFound = conversation.error instanceof ApiError && conversation.error.code === 'not_found'
    return (
      <div className="page">
        <div className={`state${notFound ? '' : ' state-error'}`} role={notFound ? undefined : 'alert'}>
          <h1 style={{ fontSize: 'var(--text-lg)', marginBottom: 8 }}>
            {notFound ? 'This conversation does not exist' : 'The conversation could not be loaded'}
          </h1>
          <p>
            {notFound
              ? 'It may have been deleted. Your other conversations are listed on the left.'
              : conversation.error.message}
          </p>
          {notFound ? (
            <Link to="/" className="btn btn-primary">
              Start a new conversation
            </Link>
          ) : (
            <button type="button" className="btn" onClick={() => void conversation.refetch()}>
              Try again
            </button>
          )}
        </div>
      </div>
    )
  }

  const loadingThread = Boolean(conversationId) && conversation.isPending

  return (
    <div className="page">
      {conversationId ? (
        <ThreadHeader
          id={conversationId}
          title={conversation.data?.title}
          updatedAt={conversation.data?.updated_at}
          count={messages.length}
        />
      ) : (
        <WorkspaceIntro />
      )}

      {loadingThread && (
        <div aria-busy="true" aria-label="Loading conversation" style={{ display: 'grid', gap: 12 }}>
          <span className="skeleton" style={{ width: '60%', height: 16 }} />
          <span className="skeleton" style={{ width: '90%' }} />
          <span className="skeleton" style={{ width: '80%' }} />
        </div>
      )}

      {conversationId && conversation.isSuccess && messages.length === 0 && !pending && (
        <div className="state">
          <h2>No questions yet</h2>
          <p>Ask your first question below. The answer will list the passages it was drawn from.</p>
        </div>
      )}

      {(messages.length > 0 || pending) && (
        <ol className="thread" aria-label="Questions and answers">
          {pairTurns(messages).map((turn) => (
            <li key={turn.key} className="turn">
              {turn.question && <Question text={turn.question.content} />}
              {turn.answer && <Answer message={turn.answer} question={turn.question?.content ?? ''} />}
            </li>
          ))}
          {pending && (
            <li className="turn" aria-live="off">
              <Question text={pending.question} />
              {pending.status === 'sending' ? (
                <div className="answer-pending" role="status">
                  <span className="pending-bars" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  Searching your documents and writing the answer…
                </div>
              ) : (
                <div className="turn-failed" role="alert">
                  <p className="inline-error" style={{ color: 'inherit' }}>
                    <AlertCircle size={16} aria-hidden="true" />
                    <span>
                      <strong>Not answered.</strong> {pending.error?.message}
                    </span>
                  </p>
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={Boolean(sys.askBlock)}
                      onClick={() => send(pending.question, pending.conversationId)}
                    >
                      Retry
                    </button>
                    <span style={{ alignSelf: 'center', fontSize: 'var(--text-xs)' }}>
                      Your question is still in the box below if you want to change it.
                    </span>
                  </div>
                </div>
              )}
            </li>
          )}
        </ol>
      )}
      <div ref={endRef} />

      <div className="composer-dock" style={{ marginTop: messages.length || pending ? 32 : 0 }}>
        <Composer
          ref={composer}
          value={draft}
          onChange={setDraft}
          onSubmit={() => send(draft, pending?.conversationId)}
          sending={sending}
          block={sys.askBlock}
          maxChars={maxChars}
          placeholder={conversationId ? 'Ask a follow-up question…' : 'Ask a question about your documents…'}
        />
      </div>
    </div>
  )
}

function WorkspaceIntro() {
  const sys = useSystem()
  const nothing = sys.documentsLoaded && sys.readyCount === 0 && sys.processingCount === 0
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ask your documents</h1>
          <p>Every answer comes with the passages it was taken from, so you can check it.</p>
        </div>
      </div>
      {sys.documentsLoaded && !nothing && (
        <p className="readiness">
          <span>
            <strong>{plural(sys.readyCount, 'document')}</strong> ready to search
          </span>
          {sys.processingCount > 0 && <span>{sys.processingCount} still indexing</span>}
          {sys.failedCount > 0 && <span>{sys.failedCount} failed</span>}
          <Link to="/library">Manage library</Link>
        </p>
      )}
      {nothing && (
        <div className="state first-step">
          <h2>Start by adding documents</h2>
          <p>Questions are answered only from files you upload: policies, contracts, handbooks, reports.</p>
          <ol>
            <li>Upload PDF, Markdown or text files in the Library.</li>
            <li>Wait until each one shows “Ready”. It usually takes a few seconds.</li>
            <li>Come back here and ask in plain language.</li>
          </ol>
          <Link to="/library" className="btn btn-primary">
            <FileSearch size={16} aria-hidden="true" /> Upload documents
          </Link>
        </div>
      )}
    </>
  )
}

function ThreadHeader({
  id,
  title,
  updatedAt,
  count,
}: {
  id: string
  title?: string
  updatedAt?: string
  count: number
}) {
  const navigate = useNavigate()
  const rename = useRenameConversation()
  const del = useDeleteConversation()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [confirming, setConfirming] = useState(false)
  const trimmed = value.trim()

  return (
    <div className="thread-head">
      <div style={{ minWidth: 0, flex: 1 }}>
        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (!trimmed || trimmed.length > 120) return
              rename.mutate(
                { id, title: trimmed },
                {
                  onSuccess: () => {
                    setEditing(false)
                    announce('Conversation renamed.')
                  },
                },
              )
            }}
            style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}
          >
            <label htmlFor="thread-title" className="visually-hidden">
              Conversation title
            </label>
            <input
              id="thread-title"
              autoFocus
              value={value}
              maxLength={120}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditing(false)
              }}
              style={{
                flex: '1 1 240px',
                minWidth: 0,
                height: 36,
                padding: '0 10px',
                border: '1px solid var(--pen-blue)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-md)',
                fontWeight: 600,
              }}
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={!trimmed || rename.isPending}>
              Save
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setEditing(false)}>
              Cancel
            </button>
            {rename.error && (
              <p className="inline-error" role="alert" style={{ flexBasis: '100%' }}>
                {rename.error.message}
              </p>
            )}
          </form>
        ) : (
          <h1>{title ?? 'Conversation'}</h1>
        )}
        {!editing && updatedAt && (
          <p className="meta">
            {plural(Math.ceil(count / 2), 'question')} · last activity {formatDateTime(updatedAt)}
          </p>
        )}
      </div>
      {!editing && title && (
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            type="button"
            className="icon-btn"
            aria-label="Rename conversation"
            title="Rename"
            onClick={() => {
              rename.reset()
              setValue(title)
              setEditing(true)
            }}
          >
            <Pencil size={16} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="icon-btn danger"
            aria-label="Delete conversation"
            title="Delete"
            onClick={() => {
              del.reset()
              setConfirming(true)
            }}
          >
            <Trash2 size={16} aria-hidden="true" />
          </button>
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        title={`Delete “${title ?? ''}”?`}
        confirmLabel="Delete conversation"
        busy={del.isPending}
        error={del.error?.message ?? null}
        onCancel={() => setConfirming(false)}
        onConfirm={() =>
          del.mutate(id, {
            onSuccess: () => {
              setConfirming(false)
              announce('Conversation deleted.')
              navigate('/')
            },
          })
        }
      >
        <p>The questions, answers and quoted passages in this conversation are removed. Your documents are not affected.</p>
      </ConfirmDialog>
    </div>
  )
}

function Question({ text }: { text: string }) {
  return (
    <div>
      <span className="question-label">Question</span>
      <p className="question">{text}</p>
    </div>
  )
}

function Answer({ message, question }: { message: Message; question: string }) {
  if (message.grounded === false) {
    return (
      <div className="answer not-grounded">
        <span className="answer-flag">
          <SearchX size={14} aria-hidden="true" /> Not found in your documents
        </span>
        <p className="answer-text">{message.content}</p>
        <p style={{ marginTop: 8, fontSize: 'var(--text-sm)', color: 'var(--ink-2)' }}>
          No passage matched this question closely enough, so no source is shown. Try other words, or check that the
          right document is in the Library.
        </p>
      </div>
    )
  }
  return (
    <div className="answer" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <span className="answer-label">Answer</span>
        <p className="answer-text">{message.content}</p>
      </div>
      {message.citations.length > 0 && <Sources citations={message.citations} question={question} />}
    </div>
  )
}

interface Turn {
  key: string
  question?: Message
  answer?: Message
}

/** Pair messages oldest-first into question/answer turns. */
export function pairTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = []
  for (const m of messages) {
    if (m.role === 'user') turns.push({ key: `q${m.id}`, question: m })
    else {
      const last = turns[turns.length - 1]
      if (last && !last.answer) last.answer = m
      else turns.push({ key: `a${m.id}`, answer: m })
    }
  }
  return turns
}
