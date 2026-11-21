import { useCallback, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  createDatasetInCatalog,
  fetchCatalog,
  listDatasets,
  updateCatalog,
  withdrawCatalog,
  type CatalogDetail,
  type CatalogUpdate,
  type DatasetPage,
} from '../api'
import { useAuth } from '../auth/useAuth'
import { canEdit } from '../auth/roles'
import { lastSegment, NOT_STATED, resourceLabel } from '../catalog/labels'
import { readCatalogParams } from '../catalog/urlState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { CopyUriButton } from '../components/CopyUriButton'
import { DatasetCardView } from '../components/DatasetCardView'
import { GoneView } from '../components/GoneView'
import { Notice } from '../components/Notice'
import { Pager } from '../components/Pager'
import { TypeTag } from '../components/Tags'
import { getBaseUri } from '../config'
import { conflictDatasets, CRUD_TEXT, describeError } from '../crud/errors'
import { datasetCount } from '../crud/labels'
import { datasetRoute, noticeState } from '../crud/navigation'
import { ResourceForm, type ResourceFormValues } from '../crud/ResourceForm'
import { useApiLoad } from '../hooks/useApiLoad'
import { PAGE_SIZE } from './CatalogPage'
import '../styles/catalog.css'
import '../styles/dataset.css'
import '../styles/crud.css'

type Panel = 'none' | 'edit' | 'new-dataset'

function pageCount(page: DatasetPage | null): number {
  if (!page || page.page_size <= 0) return 1
  return Math.max(1, Math.ceil(page.total / page.page_size))
}

/**
 * Ficha de un catálogo (`/catalogos/:slug`, destino del 303 de
 * `catalogo/{slug}`): metadatos y sus datasets (`GET /datasets?catalog=`).
 * El editor y el admin pueden editarlo, crear un dataset en él y darlo de
 * baja. Un 410 muestra la ficha mínima de la baja.
 */
export function CatalogDetailPage() {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const { page } = readCatalogParams(searchParams)

  const detailLoader = useCallback((signal: AbortSignal) => fetchCatalog(slug, signal), [slug])
  const { state, lastData, retry } = useApiLoad(detailLoader)
  // Tras editar se vuelve a pedir la ficha: mientras tanto se sigue mostrando la anterior.
  const shown = state.status === 'ok' ? state.data : state.status === 'loading' && lastData?.slug === slug ? lastData : null
  const datasetsLoader = useCallback(
    (signal: AbortSignal) => listDatasets({ catalog: slug, page, pageSize: PAGE_SIZE }, signal),
    [slug, page],
  )
  const datasets = useApiLoad(shown ? datasetsLoader : null)

  if (!shown && (state.status === 'loading' || state.status === 'idle')) {
    return (
      <p role="status" className="state">
        Cargando catálogo…
      </p>
    )
  }
  if (state.status === 'gone') return <GoneView gone={state.gone} />
  if (state.status === 'not-found') {
    return (
      <div className="dataset">
        <Breadcrumbs />
        <h1 className="page-title">Catálogo no encontrado</h1>
        <p className="muted">
          No existe ningún catálogo en esta dirección. <Link to="/catalogos">Ver los catálogos</Link>
        </p>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className="dataset">
        <Breadcrumbs />
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar el catálogo.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      </div>
    )
  }

  if (!shown) return null

  return (
    <CatalogView
      catalog={shown}
      onChanged={() => {
        retry()
        datasets.retry()
      }}
      datasets={datasets.state.status === 'ok' ? datasets.state.data : null}
      datasetsStatus={datasets.state.status}
      retryDatasets={datasets.retry}
      params={searchParams}
      page={page}
    />
  )
}

function Breadcrumbs({ title }: { title?: string }) {
  return (
    <nav aria-label="Migas de pan" className="breadcrumbs">
      <Link to="/">Catálogo</Link>
      <span aria-hidden="true">/</span>
      <Link to="/catalogos">Catálogos</Link>
      {title && (
        <>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{title}</span>
        </>
      )}
    </nav>
  )
}

interface CatalogViewProps {
  catalog: CatalogDetail
  onChanged: () => void
  datasets: DatasetPage | null
  datasetsStatus: string
  retryDatasets: () => void
  params: URLSearchParams
  page: number
}

function CatalogView({ catalog, onChanged, datasets, datasetsStatus, retryDatasets, params, page }: CatalogViewProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const [panel, setPanel] = useState<Panel>('none')
  const [saved, setSaved] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<{ message: string; datasets: string[] } | null>(null)
  const editButton = useRef<HTMLButtonElement>(null)
  const newButton = useRef<HTMLButtonElement>(null)

  const title = catalog.title ?? catalog.slug
  const base = getBaseUri()
  const totalPages = pageCount(datasets)
  const initial: ResourceFormValues = {
    slug: catalog.slug,
    title: catalog.title ?? '',
    description: catalog.description ?? '',
    publisher_name: catalog.publisher?.label ?? '',
    catalog: '',
  }

  function closePanel(focus: HTMLButtonElement | null) {
    setPanel('none')
    focus?.focus()
  }

  async function handleEdit(values: ResourceFormValues) {
    const body: CatalogUpdate = {}
    if (values.title.trim() !== initial.title) body.title = values.title.trim()
    if (values.description.trim() !== initial.description) body.description = values.description.trim()
    if (values.publisher_name.trim() !== initial.publisher_name) body.publisher_name = values.publisher_name.trim()
    if (Object.keys(body).length > 0) await updateCatalog(catalog.slug, body, token ?? '')
    setSaved(Object.keys(body).length > 0 ? 'Cambios guardados.' : 'No había cambios que guardar.')
    closePanel(editButton.current)
    onChanged()
  }

  async function handleNewDataset(values: ResourceFormValues) {
    const created = await createDatasetInCatalog(
      catalog.slug,
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

  async function handleWithdraw() {
    setWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawCatalog(catalog.slug, token ?? '')
      navigate('/catalogos', { state: noticeState(`Catálogo «${title}» dado de baja.`) })
    } catch (error) {
      const blocking = conflictDatasets(error)
      const message =
        blocking.length > 0
          ? CRUD_TEXT.catalogHasDatasets
          : describeError(error, {
              notFound: 'El catálogo no existe.',
              fallback: 'No se ha podido dar de baja el catálogo.',
            }).message
      setWithdrawError({ message, datasets: blocking })
      setWithdrawing(false)
    }
  }

  return (
    <div className="catalog">
      <Breadcrumbs title={title} />

      <header className="catalog__header crud-header">
        <div className="crud-header__text">
          <div className="dataset__tags">
            <TypeTag>dcat:Catalog</TypeTag>
          </div>
          <h1 className="page-title catalog__title">{title}</h1>
          {catalog.description && <p className="catalog__intro">{catalog.description}</p>}
          <div className="dataset__uri-row">
            <span className="mono dataset__uri">{catalog.uri}</span>
            <CopyUriButton uri={catalog.uri} />
          </div>
          <dl className="fields fields--inline">
            <div>
              <dt className="mono">dct:publisher</dt>
              <dd>{resourceLabel(catalog.publisher, NOT_STATED)}</dd>
            </div>
          </dl>
        </div>
        {editor && (
          <div className="crud-actions" role="group" aria-label="Acciones del catálogo">
            <button
              ref={editButton}
              type="button"
              className="button button--secondary"
              aria-expanded={panel === 'edit'}
              onClick={() => {
                setSaved(null)
                setPanel(panel === 'edit' ? 'none' : 'edit')
              }}
            >
              Editar catálogo
            </button>
            <button
              ref={newButton}
              type="button"
              className="button button--primary"
              aria-expanded={panel === 'new-dataset'}
              onClick={() => {
                setSaved(null)
                setPanel(panel === 'new-dataset' ? 'none' : 'new-dataset')
              }}
            >
              Nuevo dataset
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
      </header>

      <Notice />
      {saved && (
        <p role="status" className="notice">
          {saved}
        </p>
      )}

      {editor && panel === 'edit' && (
        <ResourceForm
          heading="Editar catálogo"
          mode="edit"
          initial={initial}
          requirePublisher
          submitLabel="Guardar cambios"
          errorContext={{ notFound: 'El catálogo no existe.', fallback: 'No se han podido guardar los cambios.' }}
          onSubmit={handleEdit}
          onCancel={() => closePanel(editButton.current)}
        />
      )}

      {editor && panel === 'new-dataset' && (
        <ResourceForm
          heading="Nuevo dataset en este catálogo"
          mode="create"
          initial={{ ...initial, slug: '', title: '', description: '', publisher_name: '' }}
          requirePublisher={false}
          uriPrefix={base ? `${base}dataset/` : ''}
          submitLabel="Crear dataset"
          errorContext={{ notFound: 'El catálogo no existe.', fallback: 'No se ha podido crear el dataset.' }}
          onSubmit={handleNewDataset}
          onCancel={() => closePanel(newButton.current)}
        />
      )}

      <div className="section-bar">
        <h2 className="section-bar__title">Datasets</h2>
        <span className="section-bar__count" aria-live="polite">
          {datasets ? datasetCount(datasets.total) : ''}
        </span>
      </div>

      {datasetsStatus === 'loading' && (
        <p role="status" className="state">
          Cargando datasets…
        </p>
      )}
      {(datasetsStatus === 'error' || datasetsStatus === 'not-found' || datasetsStatus === 'gone') && (
        <div role="alert" className="state state--error">
          <p>No se han podido cargar los datasets del catálogo.</p>
          <button type="button" className="button button--secondary" onClick={retryDatasets}>
            Reintentar
          </button>
        </div>
      )}
      {datasets && datasets.items.length === 0 && (
        <p className="state state--empty">Este catálogo todavía no tiene datasets.</p>
      )}
      {datasets && datasets.items.length > 0 && (
        <ul className="cards" aria-label="Datasets del catálogo">
          {datasets.items.map((item) => (
            <li key={item.slug}>
              <DatasetCardView item={item} />
            </li>
          ))}
        </ul>
      )}
      {datasets && (totalPages > 1 || page > 1) && <Pager params={params} page={page} totalPages={totalPages} />}

      {confirming && (
        <ConfirmDialog
          title="Dar de baja el catálogo"
          confirmLabel="Dar de baja"
          busy={withdrawing}
          error={
            withdrawError && (
              <>
                <p>{withdrawError.message}</p>
                {withdrawError.datasets.length > 0 && (
                  <ul className="form__issues" aria-label="Datasets que siguen en el catálogo">
                    {withdrawError.datasets.map((uri) => (
                      <li key={uri}>
                        <Link to={datasetRoute(lastSegment(uri))}>{lastSegment(uri)}</Link>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )
          }
          onConfirm={handleWithdraw}
          onCancel={() => setConfirming(false)}
        >
          <p>
            «{title}» dejará de aparecer en los listados y en las consultas SPARQL, y su URI responderá que se dio de
            baja. Su slug no se podrá reutilizar.
          </p>
          <p>Solo se puede dar de baja un catálogo vacío: antes hay que mover o dar de baja sus datasets.</p>
        </ConfirmDialog>
      )}
    </div>
  )
}
