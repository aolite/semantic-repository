import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { isAbortError, listDatasets, type DatasetCard, type DatasetPage, type DomainSlug } from '../api'
import { accessLabel, DOMAINS, DOMAIN_SLUGS, formatsLine, resourceCount, themeLabel } from '../catalog/labels'
import { DomainTag, SyntheticTag, TypeTag } from '../components/Tags'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import '../styles/catalog.css'

/** Espera tras la última pulsación antes de lanzar `q`. */
export const SEARCH_DEBOUNCE_MS = 300

/**
 * Tamaño de página pedido a la API (máximo del contrato). La interfaz de
 * paginación queda pendiente: en G2 hay pocos datasets.
 */
const PAGE_SIZE = 100

type DomainFilter = 'all' | DomainSlug
type TypeFilter = 'all' | 'dataset' | 'vocab'

const DOMAIN_CHIPS: { id: DomainFilter; label: string }[] = [
  { id: 'all', label: 'Todos los dominios' },
  ...DOMAIN_SLUGS.map((slug) => ({ id: slug, label: DOMAINS[slug].label })),
]

const TYPE_CHIPS: { id: TypeFilter; label: string }[] = [
  { id: 'all', label: 'Todo' },
  { id: 'dataset', label: 'Datasets' },
  { id: 'vocab', label: 'Vocabularios y ontologías' },
]

interface Result {
  key: string
  data?: DatasetPage
  error?: boolean
}

export function CatalogPage() {
  const [query, setQuery] = useState('')
  const [domain, setDomain] = useState<DomainFilter>('all')
  const [type, setType] = useState<TypeFilter>('all')
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const q = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS)

  // Los vocabularios y ontologías llegan en la fase 3: con ese filtro no se pide nada.
  const fetchesDatasets = type !== 'vocab'
  const requestKey = JSON.stringify({ q, domain, reload })

  useEffect(() => {
    if (!fetchesDatasets) return
    const controller = new AbortController()
    listDatasets({ q, domain: domain === 'all' ? undefined : domain, pageSize: PAGE_SIZE }, controller.signal)
      .then((data) => setResult({ key: requestKey, data }))
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        setResult({ key: requestKey, error: true })
      })
    return () => controller.abort()
  }, [fetchesDatasets, q, domain, requestKey])

  const current = result?.key === requestKey ? result : null
  const loading = fetchesDatasets && !current
  const items: DatasetCard[] = fetchesDatasets ? (current?.data?.items ?? []) : []
  const total = fetchesDatasets ? (current?.data?.total ?? 0) : 0
  const failed = fetchesDatasets && current?.error === true

  return (
    <div className="catalog">
      <header className="catalog__header">
        <span className="eyebrow mono">dcat:Catalog · itot-catalogo</span>
        <h1 className="page-title catalog__title">Datasets y vocabularios controlados</h1>
        <p className="catalog__intro">
          Punto único para publicar, describir y enlazar los datos de la unidad. Cada recurso se describe con
          DCAT-AP y se clasifica con los esquemas SKOS de IT, OT/ICS, PQC e identidad, e IA adversaria.
        </p>
      </header>

      <div className="catalog__filters">
        <label htmlFor="busqueda" className="catalog__search-label">
          Buscar en el catálogo
        </label>
        <div className="catalog__search">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" focusable="false">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
          <input
            id="busqueda"
            type="search"
            placeholder="Título, concepto o URI"
            maxLength={200}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="catalog__filter-row">
          <div role="group" aria-label="Dominio" className="chips">
            {DOMAIN_CHIPS.map((chip) => (
              <button
                key={chip.id}
                type="button"
                className="chip"
                aria-pressed={chip.id === domain}
                onClick={() => setDomain(chip.id)}
              >
                {chip.label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Tipo de recurso" className="segmented">
            {TYPE_CHIPS.map((chip) => (
              <button
                key={chip.id}
                type="button"
                className="segmented__button"
                aria-pressed={chip.id === type}
                onClick={() => setType(chip.id)}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="section-bar">
        <h2 className="section-bar__title">Recursos</h2>
        <span className="section-bar__count" aria-live="polite">
          {loading || failed ? '' : resourceCount(total)}
        </span>
      </div>

      {loading && (
        <p role="status" className="state">
          Cargando recursos…
        </p>
      )}

      {failed && (
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar el catálogo.</p>
          <button type="button" className="button button--secondary" onClick={() => setReload((n) => n + 1)}>
            Reintentar
          </button>
        </div>
      )}

      {!loading && !failed && items.length > 0 && (
        <ul className="cards" aria-label="Recursos">
          {items.map((item) => (
            <li key={item.slug}>
              <DatasetCardView item={item} />
            </li>
          ))}
        </ul>
      )}

      {!loading && !failed && items.length === 0 && (
        <p className="state state--empty">Ningún recurso coincide con los filtros.</p>
      )}
    </div>
  )
}

function DatasetCardView({ item }: { item: DatasetCard }) {
  const access = accessLabel(item.access_rights)
  const formats = formatsLine(item.formats, item.current_version)
  return (
    <article className="card">
      <div className="card__tags">
        <TypeTag>dcat:Dataset</TypeTag>
        {item.domain && <DomainTag slug={item.domain.slug} />}
        {item.synthetic && <SyntheticTag />}
        {access && <span className="card__access">{access}</span>}
      </div>
      <Link to={`/datasets/${encodeURIComponent(item.slug)}`} className="card__title">
        {item.title ?? item.slug}
      </Link>
      {item.description && <p className="card__desc">{item.description}</p>}
      {item.themes.length > 0 && (
        <ul className="card__themes" aria-label="Temas">
          {item.themes.map((theme) => (
            <li key={theme.uri} className="theme-pill">
              {themeLabel(theme)}
            </li>
          ))}
        </ul>
      )}
      {formats && (
        <div className="card__footer">
          <span className="mono card__formats">{formats}</span>
        </div>
      )}
    </article>
  )
}
