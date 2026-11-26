import { useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { listCatalogs, updateScheme, withdrawScheme, type SchemeDetail, type SchemeUpdate, type UsageRef } from '../api'
import { canEdit } from '../auth/roles'
import { useAuth } from '../auth/useAuth'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Notice } from '../components/Notice'
import { useApiLoad } from '../hooks/useApiLoad'
import { schemeRoute } from '../vocab/routes'
import { conflictUsedBy, describeError, SCHEME_INGEST_TEXT } from './errors'
import { catalogRoute, noticeState } from './navigation'
import { isManagedScheme, publishedNotice, type PublishResult } from './publish'
import { PublishRdfForm } from './PublishRdfForm'
import { ResourceForm, type ResourceFormValues } from './ResourceForm'
import { UsageList } from './UsageList'

type Panel = 'none' | 'edit' | 'republish'

interface SchemeActionsProps {
  scheme: SchemeDetail
  /** Vuelve a pedir el esquema tras editarlo o republicarlo. */
  onChanged: () => void
  /** Cabecera del navegador: las acciones van a su derecha. */
  children: ReactNode
}

/**
 * Acciones del editor y el admin en el Navegador SKOS (decisión 50):
 * «Editar» (título, descripción y publicador en español, y catálogo),
 * «Republicar» (subir el esquema completo con sus conceptos) y «Dar de baja»
 * con confirmación. El miembro y el anónimo no las ven, ni nadie en los
 * esquemas auxiliares. No están en el prototipo: [PROPUESTA].
 */
export function SchemeActions({ scheme, onChanged, children }: SchemeActionsProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token && isManagedScheme(scheme)
  const [panel, setPanel] = useState<Panel>('none')
  const [saved, setSaved] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<{ message: string; usedBy: UsageRef[] } | null>(null)
  const editButton = useRef<HTMLButtonElement>(null)
  const republishButton = useRef<HTMLButtonElement>(null)
  const catalogs = useApiLoad(editor && panel !== 'none' ? listCatalogs : null)
  const catalogItems = catalogs.state.status === 'ok' ? catalogs.state.data.items : undefined

  const title = scheme.title ?? scheme.slug
  const initial: ResourceFormValues = {
    slug: scheme.slug,
    title: scheme.title ?? '',
    description: scheme.description ?? '',
    publisher_name: scheme.metadata.publisher?.label ?? '',
    catalog: scheme.catalog?.slug ?? '',
  }

  function toggle(next: Panel) {
    setSaved(null)
    setPanel(panel === next ? 'none' : next)
  }

  function closePanel(focus: HTMLButtonElement | null) {
    setPanel('none')
    focus?.focus()
  }

  async function handleEdit(values: ResourceFormValues) {
    const body: SchemeUpdate = {}
    if (values.title.trim() !== initial.title) body.title = values.title.trim()
    if (values.description.trim() && values.description.trim() !== initial.description) {
      body.description = values.description.trim()
    }
    // Vaciar el publicador no lo borra: solo se manda si cambia a otro valor (como en los datasets).
    if (values.publisher_name.trim() && values.publisher_name.trim() !== initial.publisher_name) {
      body.publisher_name = values.publisher_name.trim()
    }
    if (values.catalog && values.catalog !== initial.catalog) body.catalog = values.catalog
    if (Object.keys(body).length > 0) await updateScheme(scheme.slug, scheme.corp, body, token ?? '')
    setSaved(
      Object.keys(body).length === 0
        ? 'No había cambios que guardar.'
        : body.catalog
          ? 'Cambios guardados. El esquema se ha movido de catálogo.'
          : 'Cambios guardados.',
    )
    closePanel(editButton.current)
    onChanged()
  }

  function handlePublished(published: PublishResult) {
    const message = publishedNotice(published)
    setPanel('none')
    if (published.kind === 'scheme' && (published.result.slug !== scheme.slug || published.result.corp !== scheme.corp)) {
      navigate(schemeRoute(published.result.slug, published.result.corp), { state: noticeState(message) })
      return
    }
    setSaved(message)
    republishButton.current?.focus()
    onChanged()
  }

  async function handleWithdraw() {
    setWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawScheme(scheme.slug, scheme.corp, token ?? '')
      const notice = noticeState(`Esquema «${title}» dado de baja.`)
      navigate(scheme.catalog ? catalogRoute(scheme.catalog.slug) : '/vocabularios', { state: notice })
    } catch (error) {
      const { message } = describeError(error, {
        notFound: 'El esquema no existe.',
        fallback: 'No se ha podido dar de baja el esquema.',
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
          <div className="crud-actions" role="group" aria-label="Acciones del esquema">
            <button
              ref={editButton}
              type="button"
              className="button button--secondary"
              aria-expanded={panel === 'edit'}
              onClick={() => toggle('edit')}
            >
              Editar
            </button>
            <button
              ref={republishButton}
              type="button"
              className="button button--primary"
              aria-expanded={panel === 'republish'}
              onClick={() => toggle('republish')}
            >
              Republicar
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

      {editor && panel === 'edit' && (
        <ResourceForm
          heading="Editar esquema"
          mode="edit"
          initial={initial}
          requirePublisher={false}
          requireDescription={!!initial.description}
          publisherHint={initial.publisher_name ? 'Si lo dejas vacío, se conserva el actual.' : undefined}
          intro={
            <p>
              Solo cambian el título y la descripción <strong>en español</strong>; las etiquetas en otros idiomas y los
              conceptos no cambian (los conceptos se cambian republicando el esquema).
            </p>
          }
          catalogs={catalogItems}
          catalogHint="Cada esquema está en un solo catálogo. Moverlo no cambia sus URIs ni las de sus conceptos."
          submitLabel="Guardar cambios"
          errorContext={{
            notFound: 'El esquema no existe.',
            fallback: 'No se han podido guardar los cambios.',
            ingestText: SCHEME_INGEST_TEXT,
          }}
          onSubmit={handleEdit}
          onCancel={() => closePanel(editButton.current)}
        />
      )}

      {editor && panel === 'republish' && token && (
        <PublishRdfForm
          kind="scheme"
          heading="Republicar el esquema"
          intro={
            <p>
              Sube el esquema completo en Turtle o JSON-LD. Tiene que traer <strong>todos los conceptos ya publicados</strong>
              : un concepto no se quita, se retira marcándolo con <span className="mono">owl:deprecated</span> (y sus
              sustitutos con <span className="mono">dct:isReplacedBy</span>). Un concepto retirado no se puede reactivar.
            </p>
          }
          catalog={scheme.catalog ?? null}
          catalogs={catalogItems}
          catalogsLoading={catalogs.state.status === 'loading'}
          submitLabel="Republicar esquema"
          token={token}
          onPublished={handlePublished}
          onCancel={() => closePanel(republishButton.current)}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title="Dar de baja el esquema"
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
            «{title}» y todos sus conceptos dejarán de aparecer en los listados y en las consultas SPARQL, y sus URIs
            responderán que se dio de baja. Su URI y su prefijo no se podrán reutilizar.
          </p>
          <p>No se puede dar de baja un esquema cuyos conceptos usan datasets, ontologías u otros esquemas publicados.</p>
        </ConfirmDialog>
      )}
    </>
  )
}
