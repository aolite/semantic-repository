/**
 * Presentación de los resultados y errores de la consola SPARQL.
 *
 * Los textos marcados como «fuera del prototipo» no salen del diseño (el
 * prototipo solo muestra resultados de ejemplo): son una propuesta del
 * frontend.
 */
import { ApiError, type SavedQuery, type SparqlJsonResults, type SparqlTerm } from '../api'

export type ResultFormat = 'table' | 'json' | 'csv'

/** Pestañas de formato del prototipo. */
export const RESULT_FORMATS: { id: ResultFormat; label: string }[] = [
  { id: 'table', label: 'Tabla' },
  { id: 'json', label: 'JSON' },
  { id: 'csv', label: 'CSV' },
]

/** Textos fuera del prototipo. */
export const SPARQL_TEXT = {
  idle: 'Ejecuta una consulta para ver los resultados.',
  running: 'Ejecutando consulta…',
  /** El prototipo usa «Sin resultados: …» con un motivo propio de su consulta de ejemplo. */
  empty: 'Sin resultados.',
  truncated: 'Resultados truncados: se muestran las primeras filas, hasta el máximo que permite el servidor.',
  emptyQuery: 'Escribe una consulta antes de ejecutarla.',
  queriesLoading: 'Cargando consultas…',
  queriesError: 'No se han podido cargar las consultas guardadas.',
  queriesEmpty: 'No hay consultas guardadas.',
} as const

/** «1 resultado» / «N resultados» (prototipo). */
export function resultCountLabel(n: number): string {
  return n === 1 ? '1 resultado' : `${n} resultados`
}

/** Texto de un término RDF en la tabla y en el CSV. */
export function termText(term: SparqlTerm | undefined): string {
  if (!term) return ''
  return term.type === 'bnode' ? `_:${term.value}` : term.value
}

/** Variables de un resultado SELECT. */
export function resultVars(data: SparqlJsonResults): string[] {
  return data.head.vars ?? []
}

/** Filas de un resultado SELECT. */
export function resultRows(data: SparqlJsonResults): Record<string, SparqlTerm>[] {
  return data.results?.bindings ?? []
}

function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/**
 * Resultado SELECT en CSV según «SPARQL 1.1 Query Results CSV and TSV
 * Formats» del W3C (cabecera sin `?`, solo valores, líneas CRLF). Se genera
 * en el navegador a partir del JSON para no repetir la consulta (cuenta para
 * el límite de frecuencia).
 */
export function toCsv(data: SparqlJsonResults): string {
  if (typeof data.boolean === 'boolean') return String(data.boolean)
  const vars = resultVars(data)
  const lines = [vars.map(csvField).join(',')]
  for (const row of resultRows(data)) {
    lines.push(vars.map((v) => csvField(termText(row[v]))).join(','))
  }
  return `${lines.join('\r\n')}\r\n`
}

/** Mensaje legible de un error de `/sparql` (fuera del prototipo). */
export function sparqlErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'No se ha podido ejecutar la consulta.'
  switch (error.status) {
    case 0:
      return 'No se ha podido conectar con la API.'
    case 400:
      return error.detail ? `La consulta no es válida: ${error.detail}` : 'La consulta no es válida.'
    case 413:
      return 'La consulta supera el tamaño máximo permitido.'
    case 429:
      return error.retryAfter !== null
        ? `Has superado el límite de consultas por minuto. Vuelve a intentarlo dentro de ${error.retryAfter} s.`
        : 'Has superado el límite de consultas por minuto. Vuelve a intentarlo en un momento.'
    case 504:
      return 'La consulta ha superado el tiempo máximo de ejecución. Prueba a acotarla, por ejemplo con LIMIT.'
    default:
      return 'No se ha podido ejecutar la consulta.'
  }
}

/** Mensaje legible de un error al guardar una consulta (fuera del prototipo). */
export function saveErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'No se ha podido guardar la consulta.'
  switch (error.status) {
    case 401:
      return 'La sesión ha caducado. Inicia sesión de nuevo para guardar.'
    case 409:
      return 'Has llegado al máximo de consultas guardadas.'
    case 413:
      return 'La consulta supera el tamaño máximo permitido.'
    case 422:
      return 'Revisa el título (hasta 120 caracteres), la pista (hasta 200) y la consulta.'
    default:
      return 'No se ha podido guardar la consulta.'
  }
}

/** Primero las de referencia y después las personales, sin cambiar el orden de la API dentro de cada grupo. */
export function sortSavedQueries(queries: SavedQuery[]): SavedQuery[] {
  return [...queries.filter((q) => q.kind === 'reference'), ...queries.filter((q) => q.kind !== 'reference')]
}
