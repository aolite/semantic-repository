import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import type { ExternalOntologyDetail, ExternalReplaceResult } from '../api'
import { canEdit } from '../auth/roles'
import { useAuth } from '../auth/useAuth'
import { externalOntologyRoute } from '../vocab/routes'
import { ExternalReplaceDialog } from './ExternalReplaceDialog'

interface ExternalOntologyActionsProps {
  ontology: ExternalOntologyDetail
  /** Vuelve a pedir la ficha tras la sustitución. */
  onChanged: () => void
  children: ReactNode
}

/**
 * Única acción sobre una ontología externa (decisión 51): «Sustituir
 * ontología», para editor y admin. No hay editar ni dar de baja (la API
 * responde 403 `not_managed`). El resultado se anuncia en una región
 * `aria-live`, que existe siempre para que los lectores de pantalla lo lean.
 */
export function ExternalOntologyActions({ ontology, onChanged, children }: ExternalOntologyActionsProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const [open, setOpen] = useState(false)
  const [announcement, setAnnouncement] = useState('')

  function handleReplaced(result: ExternalReplaceResult) {
    setOpen(false)
    setAnnouncement(`Ontología sustituida: se ha generado la versión ${result.number}, que pasa a ser la actual.`)
    // La versión nueva es la actual: se vuelve a la ficha sin `?version=` y se recarga.
    navigate(externalOntologyRoute(ontology.slug), { replace: true })
    onChanged()
  }

  return (
    <>
      <div className="crud-header">
        <div className="crud-header__text">{children}</div>
        {editor && (
          <div className="crud-actions" role="group" aria-label="Acciones de la ontología externa">
            <button
              type="button"
              className="button button--primary"
              aria-haspopup="dialog"
              onClick={() => {
                setAnnouncement('')
                setOpen(true)
              }}
            >
              Sustituir ontología
            </button>
          </div>
        )}
      </div>

      <div role="status" aria-live="polite" className={announcement ? 'notice' : 'visually-hidden'}>
        {announcement}
      </div>

      {editor && open && token && (
        <ExternalReplaceDialog
          ontology={ontology}
          token={token}
          onReplaced={handleReplaced}
          onCancel={() => setOpen(false)}
        />
      )}
    </>
  )
}
