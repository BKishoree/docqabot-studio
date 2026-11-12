import { CircleSlash, CornerDownLeft } from 'lucide-react'
import { forwardRef, useImperativeHandle, useRef } from 'react'
import { Link } from 'react-router'
import type { Block } from '../lib/system'

export interface ComposerHandle {
  focus: () => void
}

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  sending: boolean
  block: Block | null
  maxChars: number
  placeholder: string
}

/** Question input. Enter sends, Shift+Enter adds a line (DESIGN 6.4). */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { value, onChange, onSubmit, sending, block, maxChars, placeholder },
  ref,
) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => ({ focus: () => textarea.current?.focus() }))

  const trimmed = value.trim()
  const over = trimmed.length > maxChars
  const disabled = Boolean(block)
  const canSend = !disabled && !sending && trimmed.length > 0 && !over

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (canSend) onSubmit()
      }}
      aria-label="Ask a question"
    >
      <div className={`composer${disabled ? ' is-disabled' : ''}`}>
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="question"
          ref={textarea}
          value={value}
          placeholder={disabled ? 'Asking is not available right now' : placeholder}
          // Locked (not disabled) while sending so focus stays in place.
          readOnly={sending}
          disabled={disabled}
          aria-busy={sending}
          aria-describedby={`composer-hint${block ? ' composer-block' : ''}`}
          aria-invalid={over}
          rows={2}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              if (canSend) onSubmit()
            }
          }}
        />
        <div className="composer-bar">
          <span id="composer-hint" className="hint">
            {over ? (
              <span className="over">
                {trimmed.length.toLocaleString()} / {maxChars.toLocaleString()} characters. Shorten the question.
              </span>
            ) : sending ? (
              'Searching your documents and writing the answer…'
            ) : (
              <span className="hint-keys">Enter to send · Shift+Enter for a new line</span>
            )}
          </span>
          <button type="submit" className="btn btn-primary btn-sm" disabled={!canSend}>
            {sending ? 'Asking…' : 'Ask'}
            {!sending && <CornerDownLeft size={14} aria-hidden="true" />}
          </button>
        </div>
      </div>
      {block && (
        <p id="composer-block" className="composer-reason">
          <CircleSlash size={16} aria-hidden="true" />
          <span>
            {block.message}{' '}
            {block.code === 'no_ready_documents' && <Link to="/library">Go to the Library</Link>}
            {block.code === 'openai_not_configured' && <Link to="/status">See system status</Link>}
          </span>
        </p>
      )}
    </form>
  )
})
