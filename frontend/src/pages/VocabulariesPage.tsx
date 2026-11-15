import { useCallback, useState } from 'react'
import { listVocabularies, type VocabularyKind } from '../api'
import { VocabularyCardView } from '../components/VocabularyCardView'
import { useApiLoad } from '../hooks/useApiLoad'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { KIND_ORDER, KINDS, vocabularyCount } from '../vocab/labels'
import { SEARCH_DEBOUNCE_MS } from './CatalogPage'
import '../styles/catalog.css'
import '../styles/vocab.css'

type KindFilter = 'all' | VocabularyKind

const CHIPS: { id: KindFilter; label: string }[] = [
  { id: 'all', label: 'Todos' },
  ...KIND_ORDER.map((kind) => ({ id: kind, label: KINDS[kind].short })),
]

/** Pantalla «Vocabularios y ontologías» (`/vocabularios`). */
export function VocabulariesPage() {
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<KindFilter>('all')
  const q = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS)

  const loader = useCallback(
    (signal: AbortSignal) => listVocabularies({ q, kind: kind === 'all' ? undefined : kind }, signal),
    [q, kind],
  )
  const { state, lastData, retry } = useApiLoad(loader)
  const counts = lastData?.counts

  return (
    <div className="catalog">
      <header className="catalog__header">
        <span className="eyebrow mono">dcat:Catalog · itot-vocabularios</span>
        <h1 className="page-title catalog__title">Vocabularios y ontologías</h1>
        <p className="catalog__intro">
          Ontologías desarrolladas por la unidad, ontologías externas que reutilizamos y listas controladas SKOS,
          tanto corporativas de Eurecat como de dominio. Cada entrada tiene URI persistente, versión y licencia.
        </p>
      </header>

      <div role="group" aria-label="Recuento por tipo" className="vocab-stats">
        {KIND_ORDER.map((k) => (
          <button
            key={k}
            type="button"
            className="vocab-stat"
            aria-pressed={kind === k}
            onClick={() => setKind(kind === k ? 'all' : k)}
          >
            <span className="vocab-stat__n">{counts ? counts[k] : '–'}</span>{' '}
            <span className="vocab-stat__label">{KINDS[k].short}</span>
          </button>
        ))}
      </div>

      <div className="catalog__filters">
        <label htmlFor="busqueda-vocab" className="catalog__search-label">
          Buscar vocabulario
        </label>
        <div className="catalog__search">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" focusable="false">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
          <input
            id="busqueda-vocab"
            type="search"
            placeholder="Nombre, prefijo o espacio de nombres"
            maxLength={200}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div role="group" aria-label="Tipo de vocabulario" className="chips">
          {CHIPS.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className="chip"
              aria-pressed={chip.id === kind}
              onClick={() => setKind(chip.id)}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <div className="section-bar">
        <h2 className="section-bar__title">{kind === 'all' ? 'Todos los vocabularios' : KINDS[kind].short}</h2>
        <span className="section-bar__count" aria-live="polite">
          {state.status === 'ok' ? vocabularyCount(state.data.total) : ''}
        </span>
      </div>

      {state.status === 'loading' && (
        <p role="status" className="state">
          Cargando vocabularios…
        </p>
      )}

      {(state.status === 'error' || state.status === 'not-found') && (
        <div role="alert" className="state state--error">
          <p>No se han podido cargar los vocabularios.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}

      {state.status === 'ok' && state.data.items.length > 0 && (
        <ul className="cards" aria-label="Vocabularios">
          {state.data.items.map((item) => (
            <li key={`${item.kind}-${item.uri}`}>
              <VocabularyCardView item={item} />
            </li>
          ))}
        </ul>
      )}

      {state.status === 'ok' && state.data.items.length === 0 && (
        <p className="state state--empty">Ningún vocabulario coincide con los filtros.</p>
      )}
    </div>
  )
}
