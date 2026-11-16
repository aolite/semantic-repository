/**
 * Estado del Catálogo en la URL (decisión 33): búsqueda, dominio, tipo y
 * página, para que los enlaces se puedan compartir y el botón atrás funcione.
 *
 * Parámetros (en castellano, como `?version=` y `?concepto=`):
 * `q`, `dominio` (`it`, `ot`, `pqc`, `ia`), `tipo` (`datasets` o
 * `vocabularios`) y `pagina` (desde 1). Los valores por defecto no se
 * escriben y los desconocidos se ignoran.
 */
import type { DomainSlug } from '../api'
import { isDomainSlug } from './labels'

export type DomainFilter = 'all' | DomainSlug
export type TypeFilter = 'all' | 'dataset' | 'vocab'

export interface CatalogUrlState {
  q: string
  domain: DomainFilter
  type: TypeFilter
  page: number
}

export const CATALOG_PARAM = { q: 'q', domain: 'dominio', type: 'tipo', page: 'pagina' } as const

const TYPE_TO_URL: Record<Exclude<TypeFilter, 'all'>, string> = { dataset: 'datasets', vocab: 'vocabularios' }

function typeFromUrl(value: string | null): TypeFilter {
  if (value === TYPE_TO_URL.dataset) return 'dataset'
  if (value === TYPE_TO_URL.vocab) return 'vocab'
  return 'all'
}

function pageFromUrl(value: string | null): number {
  if (!value || !/^\d{1,6}$/.test(value)) return 1
  const page = Number(value)
  return page >= 1 ? page : 1
}

/** Lee el estado del Catálogo de la URL. */
export function readCatalogParams(params: URLSearchParams): CatalogUrlState {
  const domain = params.get(CATALOG_PARAM.domain)
  return {
    q: (params.get(CATALOG_PARAM.q) ?? '').trim(),
    domain: isDomainSlug(domain) ? domain : 'all',
    type: typeFromUrl(params.get(CATALOG_PARAM.type)),
    page: pageFromUrl(params.get(CATALOG_PARAM.page)),
  }
}

/**
 * Devuelve los parámetros con `changes` aplicados. Cambiar la búsqueda, el
 * dominio o el tipo vuelve a la primera página (salvo que se indique `page`).
 * Conserva los parámetros ajenos al Catálogo.
 */
export function writeCatalogParams(params: URLSearchParams, changes: Partial<CatalogUrlState>): URLSearchParams {
  const next = new URLSearchParams(params)
  const current = readCatalogParams(params)
  const state: CatalogUrlState = { ...current, ...changes }
  const filtersChanged =
    (changes.q !== undefined && changes.q.trim() !== current.q) ||
    (changes.domain !== undefined && changes.domain !== current.domain) ||
    (changes.type !== undefined && changes.type !== current.type)
  if (filtersChanged && changes.page === undefined) state.page = 1

  const set = (key: string, value: string | null) => (value ? next.set(key, value) : next.delete(key))
  set(CATALOG_PARAM.q, state.q.trim() || null)
  set(CATALOG_PARAM.domain, state.domain === 'all' ? null : state.domain)
  set(CATALOG_PARAM.type, state.type === 'all' ? null : TYPE_TO_URL[state.type])
  set(CATALOG_PARAM.page, state.page > 1 ? String(state.page) : null)
  return next
}

/** `?…` con los cambios aplicados, para un `<Link to={{ search }}>`. */
export function catalogSearch(params: URLSearchParams, changes: Partial<CatalogUrlState>): string {
  const query = writeCatalogParams(params, changes).toString()
  return query ? `?${query}` : ''
}
