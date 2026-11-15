import { describe, expect, it } from 'vitest'
import { textResponse } from '../test/fixtures'
import { jsonResponse, mockFetch } from '../test/utils'
import {
  ApiError,
  apiHref,
  createSavedQuery,
  fetchHealth,
  listDatasets,
  listSavedQueries,
  requestDownloadLink,
  runSparql,
} from '.'

describe('API de la fase 4', () => {
  it('apiHref pide a la API las URIs persistentes y las rutas, y deja el resto tal cual', () => {
    expect(apiHref('http://uri.test/itot/dataset/x/1.0.0/csv/fichero')).toBe('http://api.test/dataset/x/1.0.0/csv/fichero')
    expect(apiHref('/datasets/x/versions/1.0.0/fair/report')).toBe('http://api.test/datasets/x/versions/1.0.0/fair/report')
    expect(apiHref('https://almacen.test/prefirmada?firma=1')).toBe('https://almacen.test/prefirmada?firma=1')
    // Una URL relativa al protocolo no se toma por una ruta de la API.
    expect(apiHref('//otro.test/x')).toBe('//otro.test/x')
  })

  it('ApiError recoge detail (si es texto) y Retry-After', async () => {
    mockFetch({
      '/health': () =>
        new Response(JSON.stringify({ detail: 'Demasiadas peticiones.' }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '30' },
        }),
    })
    const error = (await fetchHealth().catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(429)
    expect(error.detail).toBe('Demasiadas peticiones.')
    expect(error.retryAfter).toBe(30)
  })

  it('ApiError ignora los detail de validación (lista) y los cuerpos no JSON', async () => {
    mockFetch({ '/health': () => jsonResponse({ detail: [{ msg: 'x' }] }, 422) })
    const validation = (await fetchHealth().catch((e: unknown) => e)) as ApiError
    expect(validation.detail).toBeNull()
    expect(validation.retryAfter).toBeNull()

    mockFetch({ '/health': () => textResponse('<html>', 'text/html', 502) })
    const html = (await fetchHealth().catch((e: unknown) => e)) as ApiError
    expect(html.detail).toBeNull()
  })

  it('listDatasets envía page', async () => {
    const fetchMock = mockFetch({ '/datasets': () => jsonResponse({ items: [], total: 0, page: 3, page_size: 20 }) })
    await listDatasets({ page: 3, pageSize: 20 })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('page')).toBe('3')
    expect(url.searchParams.get('page_size')).toBe('20')
  })

  it('requestDownloadLink hace POST con Bearer y codifica los segmentos', async () => {
    const link = { url: '/dataset/a/1.0.0/b/fichero?token=t', expires_at: '2000-01-01T00:00:00Z' }
    const fetchMock = mockFetch({ '/datasets/a%20b/versions/1.0.0/distributions/c/download-link': () => jsonResponse(link) })
    await expect(requestDownloadLink('a b', '1.0.0', 'c', 'tok')).resolves.toEqual(link)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer tok')
  })

  it('runSparql distingue resultados JSON y grafos, y lee X-Result-Truncated', async () => {
    mockFetch({
      '/sparql': () =>
        new Response(JSON.stringify({ head: { vars: [] }, results: { bindings: [] } }), {
          headers: { 'Content-Type': 'application/sparql-results+json; charset=utf-8', 'X-Result-Truncated': 'true' },
        }),
    })
    await expect(runSparql('SELECT * {}')).resolves.toEqual({
      kind: 'results',
      data: { head: { vars: [] }, results: { bindings: [] } },
      truncated: true,
    })

    mockFetch({ '/sparql': () => textResponse('# grafo', 'text/turtle; charset=utf-8') })
    await expect(runSparql('CONSTRUCT {} WHERE {}', 'tok')).resolves.toEqual({
      kind: 'graph',
      text: '# grafo',
      mediaType: 'text/turtle',
      truncated: false,
    })
  })

  it('listSavedQueries manda el JWT solo si hay sesión', async () => {
    const fetchMock = mockFetch({ '/sparql/queries': () => jsonResponse([]) })
    await listSavedQueries(null)
    await listSavedQueries('tok')
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has('Authorization')).toBe(false)
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Authorization')).toBe('Bearer tok')
  })

  it('createSavedQuery manda JSON por POST', async () => {
    const fetchMock = mockFetch({ '/sparql/queries': () => jsonResponse({}, 201) })
    await createSavedQuery({ title: 't', hint: null, query: 'ASK {}' }, 'tok')
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(init?.body))).toEqual({ title: 't', hint: null, query: 'ASK {}' })
  })
})
