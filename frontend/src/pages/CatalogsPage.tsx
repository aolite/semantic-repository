import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { createCatalog, listCatalogs, type CatalogSummary } from '../api'
import { useAuth } from '../auth/useAuth'
import { canEdit } from '../auth/roles'
import { resourceLabel } from '../catalog/labels'
import { Notice } from '../components/Notice'
import { TypeTag } from '../components/Tags'
import { getBaseUri } from '../config'
import { catalogCount, datasetCount } from '../crud/labels'
import { catalogRoute, noticeState } from '../crud/navigation'
import { ResourceForm, type ResourceFormValues } from '../crud/ResourceForm'
import { useApiLoad } from '../hooks/useApiLoad'
import '../styles/catalog.css'
import '../styles/crud.css'

const EMPTY: ResourceFormValues = { slug: '', title: '', description: '', publisher_name: '', catalog: '' }

/**
 * Listado de catálogos (`/catalogos`, decisión 49): `GET /catalogs`, sin el
 * raíz ni las bajas, con su número de datasets. El editor y el admin ven
 * «Nuevo catálogo». No está en el prototipo: usa el estilo del Catálogo.
 */
export function CatalogsPage() {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const { state, retry } = useApiLoad(listCatalogs)
  const [creating, setCreating] = useState(false)
  const newButton = useRef<HTMLButtonElement>(null)

  const loading = state.status === 'loading'
  const failed = state.status === 'error' || state.status === 'not-found' || state.status === 'gone'
  const items = state.status === 'ok' ? state.data.items : []
  const base = getBaseUri()

  function closeForm() {
    setCreating(false)
    newButton.current?.focus()
  }

  async function handleCreate(values: ResourceFormValues) {
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

  return (
    <div className="catalog">
      <nav aria-label="Migas de pan" className="breadcrumbs">
        <Link to="/">Catálogo</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">Catálogos</span>
      </nav>

      <header className="catalog__header crud-header">
        <div className="crud-header__text">
          <span className="eyebrow mono">dcat:Catalog · dcat:catalog</span>
          <h1 className="page-title catalog__title">Catálogos</h1>
          <p className="catalog__intro">Cada dataset pertenece a un solo catálogo.</p>
        </div>
        {editor && (
          <div className="crud-actions">
            <button
              ref={newButton}
              type="button"
              className="button button--primary"
              aria-expanded={creating}
              onClick={() => setCreating(!creating)}
            >
              Nuevo catálogo
            </button>
          </div>
        )}
      </header>

      <Notice />

      {editor && creating && (
        <ResourceForm
          heading="Nuevo catálogo"
          mode="create"
          initial={EMPTY}
          requirePublisher
          uriPrefix={base ? `${base}catalogo/` : ''}
          submitLabel="Crear catálogo"
          errorContext={{ notFound: 'El catálogo no existe.', fallback: 'No se ha podido crear el catálogo.' }}
          onSubmit={handleCreate}
          onCancel={closeForm}
        />
      )}

      <div className="section-bar">
        <h2 className="section-bar__title">Catálogos</h2>
        <span className="section-bar__count" aria-live="polite">
          {state.status === 'ok' ? catalogCount(state.data.total) : ''}
        </span>
      </div>

      {loading && (
        <p role="status" className="state">
          Cargando catálogos…
        </p>
      )}

      {failed && (
        <div role="alert" className="state state--error">
          <p>No se han podido cargar los catálogos.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}

      {state.status === 'ok' && items.length === 0 && <p className="state state--empty">Todavía no hay catálogos.</p>}

      {items.length > 0 && (
        <ul className="cards" aria-label="Catálogos">
          {items.map((item) => (
            <li key={item.slug}>
              <CatalogCardView item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CatalogCardView({ item }: { item: CatalogSummary }) {
  return (
    <article className="card">
      <div className="card__tags">
        <TypeTag>dcat:Catalog</TypeTag>
      </div>
      <Link to={catalogRoute(item.slug)} className="card__title">
        {item.title ?? item.slug}
      </Link>
      {item.description && <p className="card__desc">{item.description}</p>}
      <div className="card__footer">
        <span className="card__formats">{resourceLabel(item.publisher, '')}</span>
        <span className="card__count">{datasetCount(item.dataset_count)}</span>
      </div>
    </article>
  )
}
