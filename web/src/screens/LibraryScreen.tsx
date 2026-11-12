import { CheckCircle2, CircleSlash, FileWarning, Loader2, Trash2, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ApiError } from '../api/client'
import { useConfig, useDeleteDocument, useDocuments, useUploadDocument } from '../api/queries'
import type { DocumentItem } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { announce } from '../lib/announce'
import { formatBytes, formatDateTime, plural } from '../lib/format'
import { useSystem } from '../lib/system'

interface QueueItem {
  key: number
  name: string
  state: 'waiting' | 'uploading' | 'done' | 'rejected'
  message?: string
}

let queueKey = 0

export function LibraryScreen() {
  const docs = useDocuments()
  const config = useConfig()
  const sys = useSystem()
  const upload = useUploadDocument()
  const del = useDeleteDocument()
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [over, setOver] = useState(false)
  const [toDelete, setToDelete] = useState<DocumentItem | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const working = useRef(false)
  const files = useRef(new Map<number, File>())

  const blocked = sys.uploadBlock
  const accept = (config.data?.allowed_extensions ?? ['.pdf', '.md', '.txt']).join(',')
  const limit = config.data?.max_upload_bytes

  // Announce documents that finish processing while the page is open.
  const previous = useRef(new Map<number, DocumentItem['status']>())
  useEffect(() => {
    if (!docs.data) return
    const prev = previous.current
    for (const d of docs.data.items) {
      const before = prev.get(d.id)
      if (before === 'processing' && d.status === 'ready') announce(`${d.filename} is ready.`)
      if (before === 'processing' && d.status === 'failed') announce(`${d.filename} failed to process.`, 'assertive')
    }
    previous.current = new Map(docs.data.items.map((d) => [d.id, d.status]))
  }, [docs.data])

  // Process the queue one request at a time.
  useEffect(() => {
    if (working.current) return
    const next = queue.find((q) => q.state === 'waiting')
    if (!next) return
    const file = files.current.get(next.key)
    if (!file) return
    working.current = true
    setQueue((q) => q.map((i) => (i.key === next.key ? { ...i, state: 'uploading' } : i)))
    upload.mutate(file, {
      onSuccess: (doc) => {
        announce(`${doc.filename} uploaded. Indexing has started.`)
        setQueue((q) => q.filter((i) => i.key !== next.key))
      },
      onError: (error) => {
        const message = error instanceof ApiError ? error.message : 'The upload failed. Try again.'
        announce(`${next.name} was not uploaded. ${message}`, 'assertive')
        setQueue((q) => q.map((i) => (i.key === next.key ? { ...i, state: 'rejected', message } : i)))
      },
      onSettled: () => {
        files.current.delete(next.key)
        working.current = false
        setQueue((q) => [...q])
      },
    })
    // upload is stable enough for this queue; re-run only when the queue changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue])

  const addFiles = (list: FileList | File[]) => {
    if (blocked) return
    const items: QueueItem[] = []
    for (const file of Array.from(list)) {
      const key = ++queueKey
      files.current.set(key, file)
      items.push({ key, name: file.name, state: 'waiting' })
    }
    if (items.length) setQueue((q) => [...q, ...items])
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const items = docs.data?.items ?? []

  return (
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p>The documents your questions are answered from. Only documents marked Ready are searched.</p>
        </div>
      </div>

      <div
        className={`dropzone${over ? ' is-over' : ''}${blocked ? ' is-blocked' : ''}`}
        onDragEnter={(e) => {
          e.preventDefault()
          if (!blocked) setOver(true)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = blocked ? 'none' : 'copy'
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
          setOver(false)
        }}
        onDrop={onDrop}
        data-testid="dropzone"
      >
        <Upload size={28} aria-hidden="true" style={{ flex: 'none', color: 'var(--ink-2)' }} />
        <div className="dropzone-text">
          <strong>{over ? 'Drop to upload' : 'Add documents'}</strong>
          <span>
            PDF, Markdown or plain text{limit ? `, up to ${formatBytes(limit)} each` : ''}. Drag files here or choose
            them. Several files are uploaded one after another.
          </span>
        </div>
        <input
          ref={fileInput}
          id="file-input"
          type="file"
          multiple
          accept={accept}
          className="visually-hidden"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={Boolean(blocked)}
          aria-describedby={blocked ? 'upload-block' : undefined}
          onClick={() => fileInput.current?.click()}
        >
          Choose files
        </button>
      </div>
      {blocked && (
        <p id="upload-block" className="composer-reason">
          <CircleSlash size={16} aria-hidden="true" />
          <span>{blocked.message}</span>
        </p>
      )}

      {queue.length > 0 && (
        <ul className="upload-queue" aria-label="Uploads">
          {queue.map((q) => (
            <li key={q.key} className={`upload-item${q.state === 'rejected' ? ' rejected' : ''}`}>
              {q.state === 'rejected' ? (
                <FileWarning size={16} aria-hidden="true" style={{ color: 'var(--pen-red)' }} />
              ) : q.state === 'uploading' ? (
                <Loader2 size={16} className="spin" aria-hidden="true" />
              ) : (
                <Upload size={16} aria-hidden="true" style={{ color: 'var(--ink-3)' }} />
              )}
              <div className="grow">
                <div className="name">{q.name}</div>
                <div className="msg">
                  {q.state === 'rejected'
                    ? `Not uploaded: ${q.message}`
                    : q.state === 'uploading'
                      ? 'Uploading and reading the file…'
                      : 'Waiting…'}
                </div>
              </div>
              {q.state === 'rejected' && (
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Dismiss message for ${q.name}`}
                  onClick={() => setQueue((all) => all.filter((i) => i.key !== q.key))}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <section className="library-section" aria-labelledby="docs-title">
        <div className="section-head">
          <h2 id="docs-title" className="section-title">
            Documents{docs.isSuccess ? ` (${docs.data.total})` : ''}
          </h2>
          {docs.isSuccess && items.length > 0 && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-3)' }}>
              {plural(sys.readyCount, 'ready', 'ready')}
              {sys.processingCount > 0 ? ` · ${sys.processingCount} indexing` : ''}
              {sys.failedCount > 0 ? ` · ${sys.failedCount} failed` : ''}
            </span>
          )}
        </div>

        {docs.isPending && (
          <div aria-busy="true" aria-label="Loading documents" style={{ display: 'grid', gap: 12, padding: '16px 0' }}>
            <span className="skeleton" style={{ width: '100%' }} />
            <span className="skeleton" style={{ width: '100%' }} />
            <span className="skeleton" style={{ width: '70%' }} />
          </div>
        )}

        {docs.isError && (
          <div className="state state-error" role="alert">
            <h3>The document list could not be loaded</h3>
            <p>{docs.error.message}</p>
            <button type="button" className="btn" onClick={() => void docs.refetch()}>
              Try again
            </button>
          </div>
        )}

        {docs.isSuccess && items.length === 0 && (
          <div className="state">
            <h3>No documents yet</h3>
            <p>Upload a policy, contract, handbook or report above. It is ready to ask about within seconds.</p>
          </div>
        )}

        {docs.isSuccess && items.length > 0 && (
          <table className="doc-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Size
                </th>
                <th scope="col" className="num">
                  Passages
                </th>
                <th scope="col">Uploaded</th>
                <th scope="col" className="actions">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id}>
                  <td className="cell-name">
                    <div className="doc-name">{d.filename}</div>
                    {d.status === 'failed' && (
                      <p className="doc-fail">
                        {d.error?.message ?? 'The document could not be processed. Remove it and upload it again.'}
                      </p>
                    )}
                  </td>
                  <td data-label="Status">
                    <StatusPill status={d.status} />
                  </td>
                  <td className="num" data-label="Size">
                    {formatBytes(d.size_bytes)}
                  </td>
                  <td className="num" data-label="Passages">
                    {d.status === 'ready' ? d.chunk_count : '—'}
                  </td>
                  <td data-label="Uploaded">{formatDateTime(d.created_at)}</td>
                  <td className="actions">
                    <button
                      type="button"
                      className="icon-btn danger"
                      aria-label={`Delete ${d.filename}`}
                      title="Delete"
                      onClick={() => {
                        del.reset()
                        setToDelete(d)
                      }}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <ConfirmDialog
        open={toDelete !== null}
        title={`Delete “${toDelete?.filename ?? ''}”?`}
        confirmLabel="Delete document"
        busy={del.isPending}
        error={del.error instanceof ApiError ? del.error.message : null}
        onCancel={() => setToDelete(null)}
        onConfirm={() => {
          if (!toDelete) return
          const target = toDelete
          del.mutate(target.id, {
            onSuccess: () => {
              announce(`${target.filename} deleted.`)
              setToDelete(null)
            },
          })
        }}
      >
        <p>The document and its indexed passages are removed, and it is no longer used for new answers.</p>
        <p>Earlier answers keep the passages they quoted; those sources are marked as removed.</p>
      </ConfirmDialog>
    </div>
  )
}

export function StatusPill({ status }: { status: DocumentItem['status'] }) {
  if (status === 'ready')
    return (
      <span className="pill pill-ready">
        <CheckCircle2 size={13} aria-hidden="true" /> Ready
      </span>
    )
  if (status === 'processing')
    return (
      <span className="pill pill-processing">
        <Loader2 size={13} className="spin" aria-hidden="true" /> Indexing
      </span>
    )
  return (
    <span className="pill pill-failed">
      <FileWarning size={13} aria-hidden="true" /> Failed
    </span>
  )
}
