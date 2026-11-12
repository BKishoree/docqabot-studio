import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useMatch, useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import { useConversations, useDeleteConversation, useRenameConversation } from '../api/queries'
import type { ConversationSummary } from '../api/types'
import { announce } from '../lib/announce'
import { formatRelative } from '../lib/format'
import { ConfirmDialog } from './ConfirmDialog'

export function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const list = useConversations()
  const navigate = useNavigate()
  const match = useMatch('/c/:conversationId')
  const activeId = match?.params.conversationId
  const rename = useRenameConversation()
  const del = useDeleteConversation()
  const [editing, setEditing] = useState<string | null>(null)
  const [toDelete, setToDelete] = useState<ConversationSummary | null>(null)

  const confirmDelete = () => {
    if (!toDelete) return
    const target = toDelete
    del.mutate(target.id, {
      onSuccess: () => {
        announce(`Conversation “${target.title}” deleted.`)
        setToDelete(null)
        if (activeId === target.id) navigate('/')
      },
    })
  }

  return (
    <section className="convos" aria-labelledby="convos-title">
      <div className="convos-head">
        <h2 id="convos-title">Conversations</h2>
        <Link
          to="/"
          className="btn-new"
          onClick={() => {
            onNavigate?.()
          }}
        >
          <Plus size={14} aria-hidden="true" /> New
        </Link>
      </div>

      {list.isPending && (
        <div aria-busy="true" aria-label="Loading conversations">
          <span className="skeleton" style={{ width: '70%' }} />
          <span className="skeleton" style={{ width: '55%' }} />
          <span className="skeleton" style={{ width: '62%' }} />
        </div>
      )}

      {list.isError && (
        <p className="rail-note" role="alert">
          {list.error.message}{' '}
          <button type="button" onClick={() => void list.refetch()}>
            Retry
          </button>
        </p>
      )}

      {list.isSuccess && list.data.items.length === 0 && (
        <p className="rail-note">No conversations yet. Your questions and their sources are kept here.</p>
      )}

      {list.isSuccess && list.data.items.length > 0 && (
        <ul className="convo-list">
          {list.data.items.map((c) =>
            editing === c.id ? (
              <li key={c.id} className="convo">
                <RenameForm
                  conversation={c}
                  busy={rename.isPending}
                  error={rename.error instanceof ApiError ? rename.error.message : null}
                  onCancel={() => {
                    rename.reset()
                    setEditing(null)
                  }}
                  onSave={(title) =>
                    rename.mutate(
                      { id: c.id, title },
                      {
                        onSuccess: () => {
                          announce('Conversation renamed.')
                          setEditing(null)
                        },
                      },
                    )
                  }
                />
              </li>
            ) : (
              <li key={c.id} className="convo">
                <Link
                  to={`/c/${c.id}`}
                  aria-current={activeId === c.id ? 'page' : undefined}
                  onClick={() => onNavigate?.()}
                >
                  <span className="convo-title">{c.title}</span>
                  <span className="convo-meta">{formatRelative(c.updated_at)}</span>
                </Link>
                <div className="convo-actions">
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`Rename “${c.title}”`}
                    title="Rename"
                    onClick={() => {
                      rename.reset()
                      setEditing(c.id)
                    }}
                  >
                    <Pencil size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="icon-btn danger"
                    aria-label={`Delete “${c.title}”`}
                    title="Delete"
                    onClick={() => {
                      del.reset()
                      setToDelete(c)
                    }}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              </li>
            ),
          )}
        </ul>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title={`Delete “${toDelete?.title ?? ''}”?`}
        confirmLabel="Delete conversation"
        busy={del.isPending}
        error={del.error instanceof ApiError ? del.error.message : null}
        onCancel={() => setToDelete(null)}
        onConfirm={confirmDelete}
      >
        <p>The questions, answers and quoted passages in this conversation are removed. Your documents are not affected.</p>
      </ConfirmDialog>
    </section>
  )
}

function RenameForm({
  conversation,
  busy,
  error,
  onSave,
  onCancel,
}: {
  conversation: ConversationSummary
  busy: boolean
  error: string | null
  onSave: (title: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(conversation.title)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    input.current?.focus()
    input.current?.select()
  }, [])
  const trimmed = value.trim()
  const invalid = trimmed.length === 0 || trimmed.length > 120

  return (
    <form
      className="rename-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (invalid || busy) return
        if (trimmed === conversation.title) onCancel()
        else onSave(trimmed)
      }}
      style={{ flexDirection: 'column', gap: 4 }}
    >
      <label className="visually-hidden" htmlFor={`rename-${conversation.id}`}>
        New title for “{conversation.title}”
      </label>
      <input
        id={`rename-${conversation.id}`}
        ref={input}
        value={value}
        maxLength={120}
        disabled={busy}
        aria-invalid={invalid || Boolean(error)}
        aria-describedby={`rename-help-${conversation.id}`}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault()
            onCancel()
          }
        }}
        onBlur={() => {
          // Leaving the field saves a valid change; an unchanged title just closes the editor.
          if (busy) return
          if (trimmed === conversation.title) onCancel()
          else if (!invalid) onSave(trimmed)
        }}
      />
      <span id={`rename-help-${conversation.id}`} className="convo-meta" role={error ? 'alert' : undefined}>
        {error ?? (invalid ? 'Use 1 to 120 characters.' : 'Enter to save, Escape to cancel')}
      </span>
    </form>
  )
}
