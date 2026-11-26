import { useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { createCatalog, createDatasetInCatalog, type CatalogSummary } from '../api'
import { canEdit } from '../auth/roles'
import { useAuth } from '../auth/useAuth'
import { PublishMenu } from '../components/PublishMenu'
import { getBaseUri } from '../config'
import { ontologyRoute, schemeRoute } from '../vocab/routes'
import { catalogRoute, datasetRoute, noticeState } from './navigation'
import { publishedNotice, PUBLISH_OPTIONS, type PublishOption, type PublishResult } from './publish'
import { PublishRdfForm } from './PublishRdfForm'
import { ResourceForm, type ResourceFormValues } from './ResourceForm'

type Panel = 'none' | PublishOption | 'import'

const EMPTY: ResourceFormValues = { slug: '', title: '', description: '', publisher_name: '', catalog: '' }

interface PublishActionsProps {
  /** Catálogos para elegir dónde se publica (los del filtro de la pantalla). */
  catalogs: CatalogSummary[]
  catalogsLoading: boolean
  /** Cabecera de la pantalla: los botones van a su derecha. */
  children: ReactNode
}

/**
 * Botones «Importar SKOS» y «Publicar recurso» de la pantalla Catálogo
 * (prototipo; decisión 50 d), solo para editor y admin. «Publicar recurso»
 * abre un menú con nuevo catálogo, nuevo dataset, nuevo vocabulario y nueva
 * ontología; «Importar SKOS» publica un esquema desde un fichero. Los
 * formularios (que el prototipo no detalla) se abren bajo la cabecera y son
 * [PROPUESTA]: los de catálogo y dataset son los de la decisión 49.
 */
export function PublishActions({ catalogs, catalogsLoading, children }: PublishActionsProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const [panel, setPanel] = useState<Panel>('none')
  const importButton = useRef<HTMLButtonElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const base = getBaseUri()

  function close() {
    const focus = panel === 'import' ? importButton.current : menuButton.current
    setPanel('none')
    focus?.focus()
  }

  async function handleCatalog(values: ResourceFormValues) {
    const created = await createCatalog(
      {
        slug: values.slug.trim(),
        title: values.title.trim(),
        description: values.description.trim(),
        publisher_name: values.publisher_name.trim(),
      },
      token ?? '',
    )
    navigate(catalogRoute(created.slug), { state: noticeState('Catálogo creado.') })
  }

  async function handleDataset(values: ResourceFormValues) {
    const created = await createDatasetInCatalog(
      values.catalog,
      {
        slug: values.slug.trim(),
        title: values.title.trim(),
        description: values.description.trim(),
        publisher_name: values.publisher_name.trim() || null,
      },
      token ?? '',
    )
    navigate(datasetRoute(created.slug), {
      state: noticeState('Dataset creado. Publica su primera versión con «Nueva versión».'),
    })
  }

  function handlePublished(published: PublishResult) {
    const to =
      published.kind === 'scheme'
        ? schemeRoute(published.result.slug, published.result.corp)
        : ontologyRoute(published.result.slug)
    navigate(to, { state: noticeState(publishedNotice(published)) })
  }

  const schemeIntro = (
    <>
      Sube un esquema SKOS (<span className="mono">skos:ConceptScheme</span>) con sus conceptos, en Turtle o JSON-LD.
      El repositorio lo valida con las formas SHACL antes de publicarlo. Si el esquema ya existe, se republica: tiene
      que traer todos los conceptos ya publicados: un concepto no se quita, se retira con{' '}
      <span className="mono">owl:deprecated</span>.
    </>
  )

  return (
    <>
      <div className="crud-header">
        <div className="crud-header__text">{children}</div>
        {editor && (
          <div className="catalog__actions" role="group" aria-label="Publicar">
            <button
              ref={importButton}
              type="button"
              className="button button--outline catalog__action"
              aria-expanded={panel === 'import'}
              onClick={() => setPanel(panel === 'import' ? 'none' : 'import')}
            >
              Importar SKOS
            </button>
            <PublishMenu
              label="Publicar recurso"
              items={PUBLISH_OPTIONS}
              className="button button--primary catalog__action catalog__action--primary"
              buttonRef={menuButton}
              onSelect={(option) => setPanel(option)}
            />
          </div>
        )}
      </div>

      {editor && panel === 'catalog' && (
        <ResourceForm
          heading="Nuevo catálogo"
          mode="create"
          initial={EMPTY}
          requirePublisher
          uriPrefix={base ? `${base}catalogo/` : ''}
          submitLabel="Crear catálogo"
          errorContext={{ notFound: 'El catálogo no existe.', fallback: 'No se ha podido crear el catálogo.' }}
          onSubmit={handleCatalog}
          onCancel={close}
        />
      )}

      {editor && panel === 'dataset' && (
        <ResourceForm
          heading="Nuevo dataset"
          mode="create"
          initial={EMPTY}
          requirePublisher={false}
          uriPrefix={base ? `${base}dataset/` : ''}
          catalogs={catalogs}
          requireCatalog
          catalogHint={
            catalogsLoading ? 'Cargando catálogos…' : 'Cada dataset está en un solo catálogo. Después se puede mover sin cambiar sus URIs.'
          }
          submitLabel="Crear dataset"
          errorContext={{ notFound: 'El catálogo no existe.', fallback: 'No se ha podido crear el dataset.' }}
          onSubmit={handleDataset}
          onCancel={close}
        />
      )}

      {editor && token && (panel === 'scheme' || panel === 'import') && (
        <PublishRdfForm
          key={panel}
          kind="scheme"
          heading={panel === 'import' ? 'Importar SKOS' : 'Nuevo vocabulario'}
          intro={<p>{schemeIntro}</p>}
          catalogs={catalogs}
          catalogsLoading={catalogsLoading}
          submitLabel="Publicar esquema"
          token={token}
          onPublished={handlePublished}
          onCancel={close}
        />
      )}

      {editor && token && panel === 'ontology' && (
        <PublishRdfForm
          kind="ontology"
          heading="Nueva ontología"
          intro={
            <p>
              Sube una versión de una ontología propia (<span className="mono">owl:Ontology</span> con un{' '}
              <span className="mono">owl:versionIRI</span>), en Turtle o JSON-LD. El repositorio la valida con las formas
              SHACL y calcula sus métricas y su consistencia antes de publicarla. Las versiones publicadas no se pueden
              modificar.
            </p>
          }
          catalogs={catalogs}
          catalogsLoading={catalogsLoading}
          submitLabel="Publicar ontología"
          token={token}
          onPublished={handlePublished}
          onCancel={close}
        />
      )}
    </>
  )
}
