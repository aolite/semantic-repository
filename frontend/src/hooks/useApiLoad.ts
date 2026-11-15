import { useEffect, useState } from 'react'
import { ApiError, isAbortError } from '../api'

export type LoadState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'not-found' }
  | { status: 'error' }

type Loader<T> = (signal: AbortSignal) => Promise<T>

interface Result<T> {
  loader: Loader<T>
  reload: number
  state: LoadState<T>
}

/**
 * Carga un recurso de la API con `loader` (memorizado con `useCallback`: cada
 * loader nuevo lanza una petición y cancela la anterior). Un 404 o un 422 de
 * la API se tratan como «no encontrado». Con `loader` null no se pide nada.
 *
 * `lastData` conserva los últimos datos correctos mientras se carga otra
 * petición (p. ej. los recuentos al cambiar de filtro).
 */
export function useApiLoad<T>(loader: Loader<T> | null) {
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<Result<T> | null>(null)

  useEffect(() => {
    if (!loader) return
    const controller = new AbortController()
    loader(controller.signal)
      .then((data) => setResult({ loader, reload, state: { status: 'ok', data } }))
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        const notFound = error instanceof ApiError && (error.status === 404 || error.status === 422)
        setResult({ loader, reload, state: { status: notFound ? 'not-found' : 'error' } })
      })
    return () => controller.abort()
  }, [loader, reload])

  const current = result && result.loader === loader && result.reload === reload ? result.state : null
  const state: LoadState<T> = !loader ? { status: 'idle' } : (current ?? { status: 'loading' })
  const lastData = result?.state.status === 'ok' ? result.state.data : undefined

  return { state, lastData, retry: () => setReload((n) => n + 1) }
}
