import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  listCatalogs,
  listDatasets,
  listVocabularies,
  type DatasetCard,
  type DatasetPage,
  type VocabularyCard,
  type VocabularyPage,
} from '../api'
import { DOMAINS, DOMAIN_SLUGS, resourceCount } from '../catalog/labels'
import {
  readCatalogParams,
  writeCatalogParams,
  type CatalogUrlState,
  type DomainFilter,
  type TypeFilter,
} from '../catalog/urlState'
import { DatasetCardView } from '../components/DatasetCardView'
import { Notice } from '../components/Notice'
import { Pager } from '../components/Pager'
import { VocabularyCardView } from '../components/VocabularyCardView'
import { useApiLoad } from '../hooks/useApiLoad'
import '../styles/catalog.css'

/** Espera tras la última pulsación antes de lanzar `q`. */
export const SEARCH_DEBOUNCE_MS = 300

/**
 * Datasets por página (`page_size`). El prototipo no fija un número: es una
 * decisión del frontend. Los vocabularios no se paginan en la API.
 */
export const PAGE_SIZE = 20

const DOMAIN_CHIPS: { id: DomainFilter; label: string }[] = [
  { id: 'all', label: 'Todos los dominios' },
  ...DOMAIN_SLUGS.map((slug) => ({ id: slug, label: DOMAINS[slug].label })),
]

const TYPE_CHIPS: { id: TypeFilter; label: string }[] = [
  { id: 'all', label: 'Todo' },
  { id: 'dataset', label: 'Datasets' },
  { id: 'vocab', label: 'Vocabularios y ontologías' },
]

interface CatalogResult {
  datasets: DatasetPage | null
  vocabularies: VocabularyPage | null
}

type CatalogItem = { type: 'dataset'; item: DatasetCard } | { type: 'vocab'; item: VocabularyCard }

/** Número de páginas de datasets según la respuesta (al menos 1). */
function pageCount(page: DatasetPage | null | undefined): number {
  if (!page || page.page_size <= 0) return 1
  return Math.max(1, Math.ceil(page.total / page.page_size))
}

export function CatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { q, domain, type, catalog, page } = readCatalogParams(searchParams)

  // El campo de búsqueda se edita en local y llega a la URL con debounce
  // (sustituyendo la entrada del historial, para no crear una por búsqueda).
  const [input, setInput] = useState(q)
  const [syncedQ, setSyncedQ] = useState(q)
  if (q !== syncedQ) {
    // La URL ha cambiado desde fuera (atrás, adelante, un enlace): el campo la sigue.
    setSyncedQ(q)
    if (q !== input.trim()) setInput(q)
  }
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  function handleSearch(value: string) {
    setInput(value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setSearchParams((prev) => writeCatalogParams(prev, { q: value }), { replace: true })
    }, SEARCH_DEBOUNCE_MS)
  }

  // Los filtros sí crean una entrada del historial, para volver con «atrás».
  function update(changes: Partial<CatalogUrlState>) {
    setSearchParams((prev) => writeCatalogParams(prev, changes))
  }

  const fetchesDatasets = type !== 'vocab'
  // Los vocabularios no pertenecen a ningún catálogo: con un catálogo elegido solo se piden datasets.
  const fetchesVocabularies = type !== 'dataset' && !(catalog && fetchesDatasets)

  // Catálogos para el filtro (decisión 49). Si la lista falla, el filtro no se muestra.
  const catalogs = useApiLoad(listCatalogs)
  const catalogItems = catalogs.state.status === 'ok' ? catalogs.state.data.items : []

  const loader = useCallback(
    async (signal: AbortSignal): Promise<CatalogResult> => {
      const domainParam = domain === 'all' ? undefined : domain
      const [datasets, vocabularies] = await Promise.all([
        fetchesDatasets
          ? listDatasets({ q, domain: domainParam, catalog: catalog ?? undefined, page, pageSize: PAGE_SIZE }, signal)
          : null,
        fetchesVocabularies ? listVocabularies({ q, domain: domainParam }, signal) : null,
      ])
      return { datasets, vocabularies }
    },
    [fetchesDatasets, fetchesVocabularies, q, domain, catalog, page],
  )
  const { state, retry } = useApiLoad(fetchesDatasets || fetchesVocabularies ? loader : null)

  const loading = state.status === 'loading'
  const failed = state.status === 'error' || state.status === 'not-found' || state.status === 'gone'
  const data = state.status === 'ok' ? state.data : null
  const totalPages = fetchesDatasets ? pageCount(data?.datasets) : 1
  // «Todo» muestra primero los datasets y después los vocabularios y
  // ontologías, que no se paginan: van tras la última página de datasets.
  const showVocabularies = !fetchesDatasets || page >= totalPages
  const items: CatalogItem[] = [
    ...(data?.datasets?.items ?? []).map((item) => ({ type: 'dataset' as const, item })),
    ...(showVocabularies ? (data?.vocabularies?.items ?? []) : []).map((item) => ({ type: 'vocab' as const, item })),
  ]
  const total = (data?.datasets?.total ?? 0) + (data?.vocabularies?.total ?? 0)
  const showPager = !loading && !failed && fetchesDatasets && (totalPages > 1 || page > 1)

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
            value={input}
            onChange={(e) => handleSearch(e.target.value)}
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
                onClick={() => update({ domain: chip.id })}
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
                onClick={() => update({ type: chip.id })}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
        {fetchesDatasets && (catalogItems.length > 0 || catalog) && (
          <div className="catalog__catalog-row">
            <label htmlFor="filtro-catalogo" className="catalog__search-label">
              Catálogo
            </label>
            <select
              id="filtro-catalogo"
              className="select"
              value={catalog ?? ''}
              onChange={(e) => update({ catalog: e.target.value || null })}
            >
              <option value="">Todos los catálogos</option>
              {catalog && !catalogItems.some((c) => c.slug === catalog) && <option value={catalog}>{catalog}</option>}
              {catalogItems.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.title ?? c.slug}
                </option>
              ))}
            </select>
            <Link to="/catalogos" className="catalog__catalogs-link">
              Ver los catálogos
            </Link>
          </div>
        )}
      </div>

      <Notice />

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
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}

      {!loading && !failed && items.length > 0 && (
        <ul className="cards" aria-label="Recursos">
          {items.map((entry) =>
            entry.type === 'dataset' ? (
              <li key={`dataset-${entry.item.slug}`}>
                <DatasetCardView item={entry.item} />
              </li>
            ) : (
              <li key={`vocab-${entry.item.kind}-${entry.item.uri}`}>
                <VocabularyCardView item={entry.item} />
              </li>
            ),
          )}
        </ul>
      )}

      {!loading && !failed && items.length === 0 && (
        <p className="state state--empty">Ningún recurso coincide con los filtros.</p>
      )}

      {showPager && <Pager params={searchParams} page={page} totalPages={totalPages} />}
    </div>
  )
}
