import { useCallback, useState } from 'react'
import { Link } from 'react-router'
import {
  listDatasets,
  listVocabularies,
  type DatasetCard,
  type DatasetPage,
  type DomainSlug,
  type VocabularyCard,
  type VocabularyPage,
} from '../api'
import { accessLabel, DOMAINS, DOMAIN_SLUGS, formatsLine, resourceCount, themeLabel } from '../catalog/labels'
import { DomainTag, SyntheticTag, TypeTag } from '../components/Tags'
import { VocabularyCardView } from '../components/VocabularyCardView'
import { useApiLoad } from '../hooks/useApiLoad'
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

interface CatalogResult {
  datasets: DatasetPage | null
  vocabularies: VocabularyPage | null
}

type CatalogItem = { type: 'dataset'; item: DatasetCard } | { type: 'vocab'; item: VocabularyCard }

export function CatalogPage() {
  const [query, setQuery] = useState('')
  const [domain, setDomain] = useState<DomainFilter>('all')
  const [type, setType] = useState<TypeFilter>('all')
  const q = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS)

  // Las tarjetas de `/vocabularies` no traen dominio: con un dominio elegido no se pueden filtrar
  // y no se muestran (se avisa debajo de los filtros).
  const fetchesDatasets = type !== 'vocab'
  const fetchesVocabularies = type !== 'dataset' && domain === 'all'
  const vocabHiddenByDomain = type !== 'dataset' && domain !== 'all'

  const loader = useCallback(
    async (signal: AbortSignal): Promise<CatalogResult> => {
      const [datasets, vocabularies] = await Promise.all([
        fetchesDatasets
          ? listDatasets({ q, domain: domain === 'all' ? undefined : domain, pageSize: PAGE_SIZE }, signal)
          : null,
        fetchesVocabularies ? listVocabularies({ q }, signal) : null,
      ])
      return { datasets, vocabularies }
    },
    [fetchesDatasets, fetchesVocabularies, q, domain],
  )
  const { state, retry } = useApiLoad(fetchesDatasets || fetchesVocabularies ? loader : null)

  const loading = state.status === 'loading'
  const failed = state.status === 'error' || state.status === 'not-found'
  const data = state.status === 'ok' ? state.data : null
  // «Todo» muestra primero los datasets y después los vocabularios y ontologías.
  const items: CatalogItem[] = [
    ...(data?.datasets?.items ?? []).map((item) => ({ type: 'dataset' as const, item })),
    ...(data?.vocabularies?.items ?? []).map((item) => ({ type: 'vocab' as const, item })),
  ]
  const total = (data?.datasets?.total ?? 0) + (data?.vocabularies?.total ?? 0)

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
        {vocabHiddenByDomain && (
          <p className="catalog__note" role="note">
            Los vocabularios y ontologías no se filtran por dominio todavía: elige «Todos los dominios» para verlos.
          </p>
        )}
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
