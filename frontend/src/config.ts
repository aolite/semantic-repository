/**
 * Configuración del cliente leída de las variables de entorno de Vite.
 * Ningún dominio se escribe en el código: todo sale de aquí.
 */

/** Texto que muestra el prototipo cuando no hay dominio configurado. */
export const SPARQL_URL_PLACEHOLDER = '[DOMINIO]/itot/sparql'

function trimmed(value: string | undefined): string {
  return (value ?? '').trim()
}

/** URL base de la API, sin barra final. Cadena vacía si no está configurada. */
export function getApiBaseUrl(): string {
  return trimmed(import.meta.env.VITE_API_BASE_URL).replace(/\/+$/, '')
}

/** Base de las URIs persistentes, siempre con barra final. */
export function getBaseUri(): string {
  const base = trimmed(import.meta.env.VITE_BASE_URI)
  if (!base) return ''
  return base.endsWith('/') ? base : `${base}/`
}

/**
 * URL pública del endpoint SPARQL: `VITE_BASE_URI` + `sparql`.
 * Si falta la variable, devuelve el placeholder del prototipo.
 */
export function getSparqlEndpointUrl(): string {
  const base = getBaseUri()
  return base ? `${base}sparql` : SPARQL_URL_PLACEHOLDER
}
