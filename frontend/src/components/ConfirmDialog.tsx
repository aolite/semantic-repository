import { useId, useRef, type ReactNode } from 'react'
import { Dialog } from './Dialog'

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

/**
 * Diálogo modal de confirmación propio (nunca `window.confirm`), sobre
 * `Dialog`: foco inicial en «Cancelar» (la opción segura), foco atrapado
 * dentro, Escape para cancelar y vuelta del foco al control que lo abrió.
 */
export function ConfirmDialog({ title, children, confirmLabel, busy = false, error, onConfirm, onCancel }: ConfirmDialogProps) {
  const id = useId()
  const cancel = useRef<HTMLButtonElement>(null)

  return (
    <Dialog title={title} onClose={onCancel} busy={busy} initialFocus={cancel} describedBy={`${id}-body`}>
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
    </Dialog>
  )
}
