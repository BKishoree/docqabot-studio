import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { keys, useConfig, useHealth } from '../api/queries'
import type { Health } from '../api/types'
import { announce } from '../lib/announce'
import { formatBytes, formatDateTime } from '../lib/format'

export function StatusScreen() {
  const health = useHealth()
  const config = useConfig()
  const qc = useQueryClient()
  const [checking, setChecking] = useState(false)

  const checkAgain = async () => {
    setChecking(true)
    try {
      const h = await api.health(true)
      qc.setQueryData(keys.health, h)
      announce(h.status === 'ok' ? 'Check complete. All systems are ready.' : 'Check complete. Some parts need attention.')
    } catch (e) {
      announce(e instanceof Error ? e.message : 'The check failed.', 'assertive')
      void health.refetch()
    } finally {
      setChecking(false)
    }
  }

  const h = health.data
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>System status</h1>
          <p>Whether the app can store documents and reach the answer service.</p>
        </div>
        <button type="button" className="btn" onClick={() => void checkAgain()} disabled={checking}>
          <RefreshCw size={16} aria-hidden="true" className={checking ? 'spin' : undefined} />
          {checking ? 'Checking…' : 'Check again'}
        </button>
      </div>

      <section className="status-section" aria-labelledby="components-title">
        <h2 id="components-title" className="section-title">
          Components
        </h2>
        {health.isPending && (
          <div aria-busy="true" aria-label="Loading status" style={{ display: 'grid', gap: 12 }}>
            <span className="skeleton" style={{ width: '100%', height: 48 }} />
            <span className="skeleton" style={{ width: '100%', height: 48 }} />
          </div>
        )}
        {health.isError && !h && (
          <div className="state state-error" role="alert">
            <h3>The app server did not answer</h3>
            <p>{health.error.message}</p>
          </div>
        )}
        {h && (
          <dl className="status-grid">
            <div className="status-row">
              <dt>Database</dt>
              <dd>
                <ComponentState ok={h.components.database.status === 'ok'} label={h.components.database.status === 'ok' ? 'Available' : 'Unavailable'} />
                <p className="detail">
                  {h.components.database.detail ??
                    (h.components.database.status === 'ok'
                      ? 'Documents and conversations are stored and loaded normally.'
                      : 'Nothing can be loaded or saved until the database is back.')}
                </p>
              </dd>
            </div>
            <div className="status-row">
              <dt>{h.mode === 'demo' ? 'Answer service (simulated)' : 'OpenAI'}</dt>
              <dd>
                <OpenAIState health={h} />
                <p className="detail">
                  {h.components.openai.detail ?? openaiExplanation(h)} Last checked{' '}
                  {formatDateTime(h.components.openai.checked_at)}.
                </p>
              </dd>
            </div>
          </dl>
        )}
      </section>

      <section className="status-section" aria-labelledby="setup-title">
        <h2 id="setup-title" className="section-title">
          Setup
        </h2>
        {config.isError && (
          <p className="inline-error" role="alert">
            {config.error.message}
          </p>
        )}
        <dl className="kv">
          <dt>Mode</dt>
          <dd>{h ? (h.mode === 'demo' ? 'Demo: answers are simulated, no OpenAI key used' : 'Live: answers by OpenAI') : '—'}</dd>
          <dt>Version</dt>
          <dd>{h?.version ?? config.data?.version ?? '—'}</dd>
          <dt>Shared sign-in</dt>
          <dd>{h ? (h.auth_enabled ? 'On' : 'Off') : '—'}</dd>
          <dt>Upload limit</dt>
          <dd>{config.data ? `${formatBytes(config.data.max_upload_bytes)} per file` : '—'}</dd>
          <dt>File types</dt>
          <dd>{config.data ? config.data.allowed_extensions.join(', ') : '—'}</dd>
          <dt>Question length</dt>
          <dd>{config.data ? `Up to ${config.data.max_question_chars.toLocaleString()} characters` : '—'}</dd>
          <dt>Sources per answer</dt>
          <dd>
            {config.data
              ? `Up to ${config.data.retrieval.top_k}, each at least ${Math.round(config.data.retrieval.min_similarity * 100)}% match`
              : '—'}
          </dd>
          <dt>Models</dt>
          <dd>{config.data ? `${config.data.chat_model} (answers), ${config.data.embedding_model} (search)` : '—'}</dd>
        </dl>
      </section>
    </div>
  )
}

function ComponentState({ ok, label, warn = false }: { ok: boolean; label: string; warn?: boolean }) {
  if (ok)
    return (
      <span className="pill pill-ready">
        <CheckCircle2 size={13} aria-hidden="true" /> {label}
      </span>
    )
  if (warn)
    return (
      <span className="pill pill-processing">
        <CircleAlert size={13} aria-hidden="true" /> {label}
      </span>
    )
  return (
    <span className="pill pill-failed">
      <CircleX size={13} aria-hidden="true" /> {label}
    </span>
  )
}

function OpenAIState({ health }: { health: Health }) {
  const s = health.components.openai.status
  const labels: Record<string, string> = {
    ok: 'Reachable',
    not_configured: 'Not configured',
    invalid_key: 'Key rejected',
    unreachable: 'Unreachable',
    error: 'Error',
  }
  return <ComponentState ok={s === 'ok'} warn={s === 'not_configured' || s === 'error'} label={labels[s] ?? s} />
}

function openaiExplanation(h: Health): string {
  switch (h.components.openai.status) {
    case 'ok':
      return h.mode === 'demo'
        ? 'The local test service that simulates answers is running.'
        : 'Uploads can be indexed and questions answered.'
    case 'not_configured':
      return 'No API key is set. Set OPENAI_API_KEY on the server or start in demo mode.'
    case 'invalid_key':
      return 'The API key was rejected. Replace it in the server settings.'
    case 'unreachable':
      return 'The service could not be reached from the server.'
    default:
      return 'The service returned an error.'
  }
}
