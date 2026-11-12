import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Confirmation for destructive actions. Native modal <dialog>: focus is trapped
 * by the browser, Escape cancels, focus returns to the trigger on close.
 */
export function ConfirmDialog({ open, title, children, confirmLabel, busy, error, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const returnTo = useRef<Element | null>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      returnTo.current = document.activeElement
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
      cancelRef.current?.focus()
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      const target = returnTo.current
      if (target instanceof HTMLElement && target.isConnected) target.focus()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onCancel()
      }}
      onKeyDown={(e) => {
        // jsdom and older browsers: Escape still cancels.
        if (e.key === 'Escape' && !busy) {
          e.preventDefault()
          onCancel()
        }
      }}
    >
      {open && (
        <>
          <div className="dialog-body">
            <h2 id="confirm-title">{title}</h2>
            {children}
            {error && (
              <p className="inline-error" role="alert" style={{ marginTop: 12 }}>
                {error}
              </p>
            )}
          </div>
          <div className="dialog-actions">
            <button ref={cancelRef} type="button" className="btn" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
              {busy ? 'Deleting…' : confirmLabel}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
