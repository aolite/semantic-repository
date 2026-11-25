import { useLocation } from 'react-router'
import { noticeFromState } from '../crud/navigation'

/**
 * Aviso tras una acción que cambia de pantalla (p. ej. «Dataset dado de
 * baja.» al volver al catálogo). Llega en el `state` de la navegación, así
 * que desaparece al navegar de nuevo y no queda en la URL.
 */
export function Notice() {
  const notice = noticeFromState(useLocation().state)
  if (!notice) return null
  return (
    <p role="status" className="notice">
      {notice}
    </p>
  )
}
