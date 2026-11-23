import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

interface ConfirmDialogProps {
  title: string
  /** Texto de la confirmación (qué pasa si se confirma). */
  children: ReactNode
  confirmLabel: string
  /** Mientras la petición está en curso: botones inactivos (`aria-disabled`, sin perder el foco) y sin cerrar con Escape. */
  busy?: boolean
  /** Error de la última confirmación, dentro del diálogo. */
  error?: ReactNode
  onConfirm: () => void
  onCancel: () => void
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Diálogo modal de confirmación propio (nunca `window.confirm`): patrón
 * «dialog» de WAI-ARIA con `aria-modal`, foco inicial en «Cancelar» (la
 * opción segura), foco atrapado dentro, Escape para cancelar y vuelta del
 * foco al control que lo abrió.
 */
export function ConfirmDialog({ title, children, confirmLabel, busy = false, error, onConfirm, onCancel }: ConfirmDialogProps) {
  const id = useId()
  const dialog = useRef<HTMLDivElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    cancel.current?.focus()
    return () => {
      if (previous?.isConnected) previous.focus()
    }
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation()
      if (!busy) onCancel()
      return
    }
    if (event.key !== 'Tab' || !dialog.current) return
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-body`}
        className="dialog"
        onKeyDown={handleKeyDown}
      >
        <h2 id={`${id}-title`} className="panel__title">
          {title}
        </h2>
        <div id={`${id}-body`} className="dialog__body">
          {children}
        </div>
        {error && (
          <div role="alert" className="form__error">
            {error}
          </div>
        )}
        <div className="dialog__actions">
          <button ref={cancel} type="button" className="button button--secondary" onClick={() => !busy && onCancel()} aria-disabled={busy || undefined}>
            Cancelar
          </button>
          <button
            type="button"
            className="button button--danger"
            onClick={() => !busy && onConfirm()}
            aria-disabled={busy || undefined}
            aria-busy={busy || undefined}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
