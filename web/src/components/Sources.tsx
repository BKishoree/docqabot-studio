import { ChevronDown, FileX2 } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import type { Citation } from '../api/types'
import { formatRelevance, relevancePercent } from '../lib/format'
import { highlightSegments, questionTerms } from '../lib/highlight'

/** Ranked passages behind one answer. The highlighter marks the question's words. */
export function Sources({ citations, question }: { citations: Citation[]; question: string }) {
  const terms = useMemo(() => questionTerms(question), [question])
  const headingId = useId()
  const sorted = useMemo(() => [...citations].sort((a, b) => a.rank - b.rank), [citations])
  return (
    <section className="sources" aria-labelledby={headingId}>
      <div className="sources-head">
        <h3 id={headingId} className="section-title">
          Sources ({sorted.length})
        </h3>
        <span className="hint">Highlighted: words from your question</span>
      </div>
      <ol className="cite-list">
        {sorted.map((c, i) => (
          <CitationItem key={`${c.rank}-${c.filename}`} citation={c} terms={terms} defaultOpen={i === 0} />
        ))}
      </ol>
    </section>
  )
}

export function CitationItem({
  citation,
  terms,
  defaultOpen = false,
}: {
  citation: Citation
  terms: string[]
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const pct = relevancePercent(citation.similarity)
  const segments = useMemo(() => (open ? highlightSegments(citation.text, terms) : []), [open, citation.text, terms])
  const removed = !citation.document_available

  return (
    <li className="cite">
      <span className="cite-rank" aria-hidden="true">
        {citation.rank}
      </span>
      <div>
        <button
          type="button"
          className="cite-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`Source ${citation.rank}: ${citation.filename}, ${formatRelevance(citation.similarity)}${
            removed ? ', removed from library' : ''
          }`}
          onClick={() => setOpen((v) => !v)}
        >
          <span className={`cite-file${removed ? ' removed' : ''}`}>{citation.filename}</span>
          <span className="cite-meta">
            {removed && (
              <span className="removed-tag">
                <FileX2 size={13} aria-hidden="true" /> Removed from library
              </span>
            )}
            <span className="relevance" title="How closely this passage matches your question">
              <span className="relevance-bar" aria-hidden="true">
                <span style={{ width: `${pct}%` }} />
              </span>
              {formatRelevance(citation.similarity)}
            </span>
            <ChevronDown size={16} className="cite-chevron" aria-hidden="true" />
          </span>
        </button>
        <div id={bodyId} className="cite-body" hidden={!open}>
          {open && (
            <>
              <blockquote className="passage">
                {segments.map((s, i) => (s.marked ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>))}
              </blockquote>
              <p className="passage-foot">
                <span>Quoted as stored when the answer was written</span>
                {citation.chunk_index !== null && <span>Passage {citation.chunk_index + 1} of the document</span>}
                {removed && <span>The document has since been deleted; this quote is kept with the answer.</span>}
              </p>
            </>
          )}
        </div>
      </div>
    </li>
  )
}
