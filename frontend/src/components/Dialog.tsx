import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react'

interface DialogProps {
  title: string
  children: ReactNode
  /** Escape (si no está `busy`). */
  onClose: () => void
  /** Mientras hay una petición en curso, Escape no cierra. */
  busy?: boolean
  /** Control que recibe el foco al abrir; por defecto, el primero enfocable. */
  initialFocus?: RefObject<HTMLElement | null>
  /** `aria-describedby` del diálogo (el id de su texto principal). */
  describedBy?: string
  /** Clase adicional (p. ej. un diálogo más ancho con formulario). */
  className?: string
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Diálogo modal propio: patrón «dialog» de WAI-ARIA con `aria-modal`, foco
 * inicial dentro, foco atrapado, Escape para cerrar y vuelta del foco al
 * control que lo abrió. Lo usan la confirmación (`ConfirmDialog`) y
 * «Sustituir ontología» de las externas.
 */
export function Dialog({ title, children, onClose, busy = false, initialFocus, describedBy, className }: DialogProps) {
  const id = useId()
  const dialog = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const target = initialFocus?.current ?? dialog.current?.querySelector<HTMLElement>(FOCUSABLE) ?? null
    target?.focus()
    return () => {
      if (previous?.isConnected) previous.focus()
    }
    // Solo al abrir: el foco inicial no se recoloca en cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation()
      if (!busy) onClose()
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
        aria-describedby={describedBy}
        className={className ? `dialog ${className}` : 'dialog'}
        onKeyDown={handleKeyDown}
      >
        <h2 id={`${id}-title`} className="panel__title">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}
