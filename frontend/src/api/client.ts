import { getApiBaseUrl, getBaseUri } from '../config'

/** Error de la API con el código HTTP (0 si no hubo respuesta). */
export class ApiError extends Error {
  readonly status: number
  /** `detail` de `ErrorResponse` si la API lo manda como texto. */
  readonly detail: string | null
  /** Segundos de la cabecera `Retry-After` (429), si la hay. */
  readonly retryAfter: number | null

  constructor(status: number, message: string, detail: string | null = null, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfter = retryAfter
  }
}

export interface RequestOptions {
  method?: string
  body?: BodyInit
  headers?: Record<string, string>
  token?: string
  /** Permite cancelar la petición (p. ej. al cambiar los filtros). */
  signal?: AbortSignal
}

/** Parámetros de consulta; los valores vacíos o `undefined` no se envían. */
export type QueryParams = Record<string, string | number | null | undefined>

/** Construye `path?query` omitiendo los parámetros vacíos. */
export function withQuery(path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

/**
 * URL absoluta de un recurso de la API, para enlaces que abre el navegador
 * directamente (p. ej. descargas de RDF).
 */
export function apiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`
}

/**
 * Enlace que abre el navegador para una URL que devuelve la API (descarga de
 * una distribución, informe FAIR, enlace firmado):
 *
 * - Si es una URI persistente (`VITE_BASE_URI` + ruta), se pide a la API con
 *   la misma ruta (`/dataset/…`): el backend sirve las URIs persistentes desde
 *   su raíz, y así funciona también en local, donde `BASE_URI` no resuelve.
 * - Si es una ruta (`/…`), se resuelve contra la API.
 * - En otro caso (p. ej. una URL prefirmada de R2), se usa tal cual.
 */
export function apiHref(url: string): string {
  const base = getBaseUri()
  if (base && url.startsWith(base)) return apiUrl(`/${url.slice(base.length)}`)
  if (url.startsWith('/') && !url.startsWith('//')) return apiUrl(url)
  return url
}

/** Indica si el error se debe a una petición cancelada con `AbortSignal`. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

async function send(path: string, options: RequestOptions, accept: string): Promise<Response> {
  const headers: Record<string, string> = { Accept: accept, ...options.headers }
  if (options.token) headers.Authorization = `Bearer ${options.token}`

  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      method: options.method ?? 'GET',
      body: options.body,
      headers,
      signal: options.signal,
    })
  } catch (error) {
    if (isAbortError(error) || options.signal?.aborted) throw error
    throw new ApiError(0, 'No se ha podido conectar con la API.')
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `La API ha respondido ${response.status}.`,
      await errorDetail(response),
      retryAfterSeconds(response.headers.get('Retry-After')),
    )
  }
  return response
}

/** `detail` de un `ErrorResponse` (solo si es texto; los 422 de validación traen una lista). */
async function errorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // Cuerpo vacío o no JSON.
  }
  return null
}

/** `Retry-After` en segundos (solo la forma numérica). */
function retryAfterSeconds(value: string | null): number | null {
  if (!value || !/^\d+$/.test(value.trim())) return null
  return Number(value.trim())
}

/** Llamada JSON a la API. Único punto del cliente que usa `fetch` (junto a `apiRequestText` y `apiRequestRaw`). */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options, 'application/json')
  return (await response.json()) as T
}

/**
 * Llamada a la API que devuelve la `Response` tal cual, para leer cabeceras
 * o elegir cómo interpretar el cuerpo según su `Content-Type` (SPARQL).
 */
export function apiRequestRaw(path: string, accept: string, options: RequestOptions = {}): Promise<Response> {
  return send(path, options, accept)
}

/** Llamada a la API que devuelve texto (p. ej. RDF serializado). */
export async function apiRequestText(path: string, accept: string, options: RequestOptions = {}): Promise<string> {
  const response = await send(path, options, accept)
  return response.text()
}
