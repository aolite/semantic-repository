import { useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { listCatalogs, updateOntology, withdrawOntology, type OntologyDetail, type UsageRef } from '../api'
import { canEdit } from '../auth/roles'
import { useAuth } from '../auth/useAuth'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice } from '../components/Notice'
import { useApiLoad } from '../hooks/useApiLoad'
import { ontologyRoute } from '../vocab/routes'
import { CatalogMoveForm } from './CatalogMoveForm'
import { conflictUsedBy, describeError, ONTOLOGY_INGEST_TEXT } from './errors'
import { catalogRoute, noticeState } from './navigation'
import { publishedNotice, type PublishResult } from './publish'
import { PublishRdfForm } from './PublishRdfForm'
import { UsageList } from './UsageList'

type Panel = 'none' | 'move' | 'version'

interface OntologyActionsProps {
  ontology: OntologyDetail
  onChanged: () => void
  children: ReactNode
}

/**
 * Acciones del editor y el admin en la Ficha de ontología (decisión 50):
 * «Mover de catálogo» (los metadatos van en cada versión, que es inmutable,
 * así que `PATCH` solo mueve), «Nueva versión» (subir el RDF de la versión)
 * y «Dar de baja» con confirmación. No están en el prototipo: [PROPUESTA].
 */
export function OntologyActions({ ontology, onChanged, children }: OntologyActionsProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const [panel, setPanel] = useState<Panel>('none')
  const [saved, setSaved] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<{ message: string; usedBy: UsageRef[] } | null>(null)
  const moveButton = useRef<HTMLButtonElement>(null)
  const versionButton = useRef<HTMLButtonElement>(null)
  const catalogs = useApiLoad(editor && panel !== 'none' ? listCatalogs : null)
  const catalogItems = catalogs.state.status === 'ok' ? catalogs.state.data.items : undefined

  const title = ontology.title ?? ontology.metadata.title ?? ontology.slug

  function toggle(next: Panel) {
    setSaved(null)
    setPanel(panel === next ? 'none' : next)
  }

  function closePanel(focus: HTMLButtonElement | null) {
    setPanel('none')
    focus?.focus()
  }

  async function handleMove(catalog: string) {
    await updateOntology(ontology.slug, { catalog }, token ?? '')
    setSaved('La ontología se ha movido de catálogo.')
    closePanel(moveButton.current)
    onChanged()
  }

  function handlePublished(published: PublishResult) {
    setPanel('none')
    const message = publishedNotice(published)
    if (published.kind === 'ontology' && published.result.slug !== ontology.slug) {
      navigate(ontologyRoute(published.result.slug), { state: noticeState(message) })
      return
    }
    // La versión nueva pasa a ser la actual: se vuelve a la ficha sin `?version=`.
    navigate(ontologyRoute(ontology.slug), { state: noticeState(message) })
    onChanged()
  }

  async function handleWithdraw() {
    setWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawOntology(ontology.slug, token ?? '')
      const notice = noticeState(`Ontología «${title}» dada de baja.`)
      navigate(ontology.catalog ? catalogRoute(ontology.catalog.slug) : '/vocabularios', { state: notice })
    } catch (error) {
      const { message } = describeError(error, {
        notFound: 'La ontología no existe.',
        fallback: 'No se ha podido dar de baja la ontología.',
      })
      setWithdrawError({ message, usedBy: conflictUsedBy(error) })
      setWithdrawing(false)
    }
  }

  return (
    <>
      <div className="crud-header">
        <div className="crud-header__text">{children}</div>
        {editor && (
          <div className="crud-actions" role="group" aria-label="Acciones de la ontología">
            <button
              ref={moveButton}
              type="button"
              className="button button--secondary"
              aria-expanded={panel === 'move'}
              onClick={() => toggle('move')}
            >
              Mover de catálogo
            </button>
            <button
              ref={versionButton}
              type="button"
              className="button button--primary"
              aria-expanded={panel === 'version'}
              onClick={() => toggle('version')}
            >
              Nueva versión
            </button>
            <button
              type="button"
              className="button button--danger-outline"
              onClick={() => {
                setWithdrawError(null)
                setConfirming(true)
              }}
            >
              Dar de baja
            </button>
          </div>
        )}
      </div>

      <Notice />
      {saved && (
        <p role="status" className="notice">
          {saved}
        </p>
      )}

      {editor && panel === 'move' && (
        <CatalogMoveForm
          heading="Mover la ontología de catálogo"
          intro={
            <p>
              Los metadatos de una ontología van en cada versión, que no se puede modificar: para cambiarlos, publica una
              versión nueva.
            </p>
          }
          current={ontology.catalog?.slug ?? ''}
          catalogs={catalogItems}
          catalogsLoading={catalogs.state.status === 'loading'}
          errorContext={{
            notFound: 'La ontología o el catálogo no existen.',
            fallback: 'No se ha podido mover la ontología.',
            ingestText: ONTOLOGY_INGEST_TEXT,
          }}
          onSubmit={handleMove}
          onCancel={() => closePanel(moveButton.current)}
        />
      )}

      {editor && panel === 'version' && token && (
        <PublishRdfForm
          kind="ontology"
          heading="Nueva versión de la ontología"
          intro={
            <p>
              Sube la versión nueva en Turtle o JSON-LD, con un <span className="mono">owl:versionIRI</span> que no esté
              publicado. El repositorio la valida con las formas SHACL y calcula sus métricas y su consistencia; las
              versiones publicadas no se pueden modificar.
            </p>
          }
          catalog={ontology.catalog ?? null}
          catalogs={catalogItems}
          catalogsLoading={catalogs.state.status === 'loading'}
          submitLabel="Publicar versión"
          token={token}
          onPublished={handlePublished}
          onCancel={() => closePanel(versionButton.current)}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title="Dar de baja la ontología"
          confirmLabel="Dar de baja"
          busy={withdrawing}
          error={
            withdrawError && (
              <>
                <p>{withdrawError.message}</p>
                <UsageList usedBy={withdrawError.usedBy} />
              </>
            )
          }
          onConfirm={handleWithdraw}
          onCancel={() => setConfirming(false)}
        >
          <p>
            «{title}» y <strong>todas sus versiones</strong> dejarán de aparecer en los listados y en las consultas SPARQL,
            y sus URIs responderán que se dio de baja. Su URI y su prefijo no se podrán reutilizar.
          </p>
          <p>No se puede dar de baja una ontología que importan o usan otras ontologías publicadas.</p>
        </ConfirmDialog>
      )}
    </>
  )
}
