import { apiRequest, apiRequestRaw } from './client'
import type { SavedQuery, SavedQueryCreate } from './types'
import type { SparqlJsonResults } from '../sparql/w3c'

/** Tipo de medio de los resultados SELECT y ASK. */
export const SPARQL_RESULTS_JSON = 'application/sparql-results+json'

/**
 * `Accept` de la consola: resultados JSON para SELECT y ASK; para CONSTRUCT y
 * DESCRIBE, el backend responde con Turtle (su formato por defecto).
 */
const SPARQL_ACCEPT = `${SPARQL_RESULTS_JSON}, text/turtle;q=0.9`

/** Resultado de una ejecución en `/sparql`. */
export type SparqlRunResult =
  | { kind: 'results'; data: SparqlJsonResults; truncated: boolean }
  | { kind: 'graph'; text: string; mediaType: string; truncated: boolean }

/**
 * `POST /sparql` con el cuerpo `application/sparql-query`. Es público; con
 * sesión se manda el JWT para que se aplique el límite de usuario autenticado.
 * Los errores (400, 413, 429, 504…) llegan como `ApiError`.
 */
export async function runSparql(query: string, token?: string | null, signal?: AbortSignal): Promise<SparqlRunResult> {
  const response = await apiRequestRaw('/sparql', SPARQL_ACCEPT, {
    method: 'POST',
    body: query,
    headers: { 'Content-Type': 'application/sparql-query' },
    token: token ?? undefined,
    signal,
  })
  const truncated = response.headers.get('X-Result-Truncated')?.trim().toLowerCase() === 'true'
  const mediaType = (response.headers.get('Content-Type') ?? '').split(';')[0].trim().toLowerCase()
  if (mediaType === SPARQL_RESULTS_JSON || mediaType === 'application/json') {
    return { kind: 'results', data: (await response.json()) as SparqlJsonResults, truncated }
  }
  return { kind: 'graph', text: await response.text(), mediaType, truncated }
}

/** `GET /sparql/queries`: las de referencia y, con sesión, las personales. */
export function listSavedQueries(token?: string | null, signal?: AbortSignal): Promise<SavedQuery[]> {
  return apiRequest<SavedQuery[]>('/sparql/queries', { token: token ?? undefined, signal })
}

/** `POST /sparql/queries` (miembro): guarda una consulta personal. */
export function createSavedQuery(input: SavedQueryCreate, token: string): Promise<SavedQuery> {
  return apiRequest<SavedQuery>('/sparql/queries', {
    method: 'POST',
    body: JSON.stringify(input),
    headers: { 'Content-Type': 'application/json' },
    token,
  })
}
