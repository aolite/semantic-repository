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
}

/** Llamada JSON a la API. Único punto del cliente que usa `fetch`. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  if (options.token) headers.Authorization = `Bearer ${options.token}`

  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      method: options.method ?? 'GET',
      body: options.body,
      headers,
    })
  } catch {
    throw new ApiError(0, 'No se ha podido conectar con la API.')
  }

  if (!response.ok) {
    throw new ApiError(response.status, `La API ha respondido ${response.status}.`)
  }
  return (await response.json()) as T
}
