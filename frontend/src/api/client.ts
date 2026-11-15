import { getApiBaseUrl } from '../config'

/** Error de la API con el código HTTP (0 si no hubo respuesta). */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
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
    throw new ApiError(response.status, `La API ha respondido ${response.status}.`)
  }
  return response
}

/** Llamada JSON a la API. Único punto del cliente que usa `fetch` (junto a `apiRequestText`). */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options, 'application/json')
  return (await response.json()) as T
}

/** Llamada a la API que devuelve texto (p. ej. RDF serializado). */
export async function apiRequestText(path: string, accept: string, options: RequestOptions = {}): Promise<string> {
  const response = await send(path, options, accept)
  return response.text()
}
