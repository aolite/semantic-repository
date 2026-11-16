import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { SavedQuery, SparqlJsonResults } from '../api'
import { SPARQL_TEXT } from '../sparql/results'
import { textResponse } from '../test/fixtures'
import { jsonResponse, mockFetch, renderApp, tokenFixture, userFixture } from '../test/utils'

type Handler = Parameters<typeof mockFetch>[0][string]

function savedFixture(overrides: Partial<SavedQuery> = {}): SavedQuery {
  return {
    id: 'consulta-a',
    title: 'Consulta de prueba A',
    hint: 'Pista de prueba A',
    query: 'SELECT ?a WHERE { ?a ?b ?c }',
    kind: 'reference',
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

const REFERENCE = [
  savedFixture(),
  savedFixture({ id: 'consulta-b', title: 'Consulta de prueba B', hint: null, query: 'ASK { ?s ?p ?o }' }),
]
const PERSONAL = savedFixture({
  id: '00000000-0000-4000-8000-000000000001',
  title: 'Consulta personal',
  hint: null,
  query: 'SELECT ?x WHERE { ?x ?y ?z }',
  kind: 'personal',
  created_at: '2000-01-01T00:00:00Z',
  updated_at: '2000-01-01T00:00:00Z',
})

function selectResults(rows: number): SparqlJsonResults {
  return {
    head: { vars: ['dataset', 'titulo'] },
    results: {
      bindings: Array.from({ length: rows }, (_, i) => ({
        dataset: { type: 'uri', value: `http://uri.test/itot/dataset/d${i}` },
        titulo: { type: 'literal', value: `Título, "${i}"`, 'xml:lang': 'es' },
      })),
    },
  }
}

function sparqlResponse(body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/sparql-results+json', ...headers },
  })
}

function mockSparql(routes: { queries?: Handler; sparql?: Handler; extra?: Record<string, Handler> } = {}) {
  return mockFetch({
    '/sparql/queries': routes.queries ?? ((_url, init) => {
      const auth = new Headers(init?.headers).get('Authorization')
      return jsonResponse(auth ? [...REFERENCE, PERSONAL] : REFERENCE)
    }),
    '/sparql': routes.sparql ?? (() => sparqlResponse(selectResults(2))),
    ...routes.extra,
  })
}

async function renderConsole() {
  const result = renderApp('/sparql')
  await screen.findByRole('button', { name: /Consulta de prueba A/ })
  return result
}

function editor() {
  return screen.getByLabelText('Consulta') as HTMLTextAreaElement
}

function resultsSection() {
  return screen.getByRole('heading', { level: 2, name: 'Resultados' }).closest('section') as HTMLElement
}

async function login(user: ReturnType<typeof renderApp>['user']) {
  await user.click(screen.getByRole('link', { name: 'Iniciar sesión' }))
  await user.type(await screen.findByLabelText('Usuario'), 'usuario-prueba')
  await user.type(screen.getByLabelText('Contraseña'), 'contrasena-prueba')
  await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))
}

describe('Consola SPARQL', () => {
  it('muestra la cabecera con el endpoint construido con VITE_BASE_URI', async () => {
    mockSparql()
    await renderConsole()
    expect(screen.getByRole('heading', { level: 1, name: 'Consulta SPARQL' })).toBeInTheDocument()
    expect(screen.getByText('Endpoint · http://uri.test/itot/sparql')).toBeInTheDocument()
  })

  it('lista las consultas de referencia, elige la primera y la carga en el editor', async () => {
    mockSparql()
    await renderConsole()
    const saved = screen.getByRole('region', { name: 'Consultas guardadas' })
    const buttons = within(saved).getAllByRole('button')
    expect(buttons.map((b) => b.textContent)).toEqual(['Consulta de prueba APista de prueba A', 'Consulta de prueba B'])
    expect(buttons[0]).toHaveAttribute('aria-pressed', 'true')
    expect(buttons[1]).toHaveAttribute('aria-pressed', 'false')
    expect(editor()).toHaveValue('SELECT ?a WHERE { ?a ?b ?c }')
    expect(within(resultsSection()).getByText(SPARQL_TEXT.idle)).toBeInTheDocument()
  })

  it('cambia de consulta conservando lo editado en cada una', async () => {
    mockSparql()
    const { user } = await renderConsole()
    await user.clear(editor())
    await user.type(editor(), 'SELECT editada')
    await user.click(screen.getByRole('button', { name: 'Consulta de prueba B' }))
    expect(screen.getByRole('button', { name: 'Consulta de prueba B' })).toHaveAttribute('aria-pressed', 'true')
    expect(editor()).toHaveValue('ASK { ?s ?p ?o }')
    await user.click(screen.getByRole('button', { name: /Consulta de prueba A/ }))
    expect(editor()).toHaveValue('SELECT editada')
  })

  it('sin sesión no muestra «Guardar»', async () => {
    mockSparql()
    await renderConsole()
    expect(screen.queryByRole('button', { name: 'Guardar' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ejecutar' })).toBeInTheDocument()
  })

  it('«Ejecutar» manda la consulta por POST a /sparql y pinta la tabla con el recuento', async () => {
    const fetchMock = mockSparql()
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))

    const results = resultsSection()
    const table = await within(results).findByRole('table')
    expect(within(results).getByText('2 resultados')).toBeInTheDocument()
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['?dataset', '?titulo'])
    expect(within(table).getByText('http://uri.test/itot/dataset/d0')).toBeInTheDocument()
    expect(within(table).getByText('Título, "1"')).toBeInTheDocument()

    const call = fetchMock.mock.calls.find(([u]) => new URL(String(u)).pathname === '/sparql')!
    expect(call[1]?.method).toBe('POST')
    expect(call[1]?.body).toBe('SELECT ?a WHERE { ?a ?b ?c }')
    const headers = new Headers(call[1]?.headers)
    expect(headers.get('Content-Type')).toBe('application/sparql-query')
    expect(headers.get('Accept')).toContain('application/sparql-results+json')
    expect(headers.has('Authorization')).toBe(false)
  })

  it('muestra «1 resultado» en singular', async () => {
    mockSparql({ sparql: () => sparqlResponse(selectResults(1)) })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    expect(await within(resultsSection()).findByText('1 resultado')).toBeInTheDocument()
  })

  it('cambia entre Tabla, JSON y CSV con aria-pressed sin repetir la consulta', async () => {
    const fetchMock = mockSparql()
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    const results = resultsSection()
    await within(results).findByRole('table')

    const group = within(results).getByRole('group', { name: 'Formato' })
    const json = within(group).getByRole('button', { name: 'JSON' })
    const csv = within(group).getByRole('button', { name: 'CSV' })
    expect(within(group).getByRole('button', { name: 'Tabla' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(json)
    expect(json).toHaveAttribute('aria-pressed', 'true')
    expect(within(results).getByLabelText('Resultados en JSON').textContent).toContain('"vars": [')

    await user.click(csv)
    expect(csv).toHaveAttribute('aria-pressed', 'true')
    expect(within(results).getByLabelText('Resultados en CSV').textContent).toBe(
      'dataset,titulo\r\nhttp://uri.test/itot/dataset/d0,"Título, ""0"""\r\nhttp://uri.test/itot/dataset/d1,"Título, ""1"""\r\n',
    )
    expect(fetchMock.mock.calls.filter(([u]) => new URL(String(u)).pathname === '/sparql')).toHaveLength(1)
  })

  it('sin filas muestra el mensaje vacío', async () => {
    mockSparql({ sparql: () => sparqlResponse(selectResults(0)) })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    const results = resultsSection()
    expect(await within(results).findByText(SPARQL_TEXT.empty)).toBeInTheDocument()
    expect(within(results).getByText('0 resultados')).toBeInTheDocument()
  })

  it('avisa si el resultado viene truncado', async () => {
    mockSparql({ sparql: () => sparqlResponse(selectResults(1), { 'X-Result-Truncated': 'true' }) })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    expect(await within(resultsSection()).findByText(SPARQL_TEXT.truncated)).toBeInTheDocument()
  })

  it('muestra el booleano de un ASK', async () => {
    mockSparql({ sparql: () => sparqlResponse({ head: {}, boolean: true }) })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Consulta de prueba B' }))
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    expect(await within(resultsSection()).findByText('true')).toBeInTheDocument()
  })

  it('muestra el Turtle de un CONSTRUCT sin las pestañas de formato', async () => {
    mockSparql({ sparql: () => textResponse('<http://uri.test/s> <http://uri.test/p> "o" .', 'text/turtle') })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    const results = resultsSection()
    expect(await within(results).findByLabelText('Grafo resultado')).toHaveTextContent('<http://uri.test/s>')
    expect(within(results).queryByRole('group', { name: 'Formato' })).not.toBeInTheDocument()
  })

  it('ejecuta con Ctrl+Intro desde el editor', async () => {
    const fetchMock = mockSparql()
    const { user } = await renderConsole()
    editor().focus()
    await user.keyboard('{Control>}{Enter}{/Control}')
    await within(resultsSection()).findByRole('table')
    expect(fetchMock.mock.calls.some(([u]) => new URL(String(u)).pathname === '/sparql')).toBe(true)
  })

  it('no manda una consulta vacía', async () => {
    const fetchMock = mockSparql()
    const { user } = await renderConsole()
    await user.clear(editor())
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    expect(within(resultsSection()).getByRole('alert')).toHaveTextContent(SPARQL_TEXT.emptyQuery)
    expect(fetchMock.mock.calls.some(([u]) => new URL(String(u)).pathname === '/sparql')).toBe(false)
  })

  it.each([
    [400, { detail: 'Error de sintaxis de prueba en la línea 1.' }, {}, 'La consulta no es válida: Error de sintaxis de prueba en la línea 1.'],
    [400, { detail: 'SERVICE no está permitido.' }, {}, 'La consulta no es válida: SERVICE no está permitido.'],
    [413, { detail: 'x' }, {}, 'La consulta supera el tamaño máximo permitido.'],
    [429, { detail: 'x' }, { 'Retry-After': '17' }, 'Has superado el límite de consultas por minuto. Vuelve a intentarlo dentro de 17 s.'],
    [429, { detail: 'x' }, {}, 'Has superado el límite de consultas por minuto. Vuelve a intentarlo en un momento.'],
    [504, { detail: 'x' }, {}, 'La consulta ha superado el tiempo máximo de ejecución. Prueba a acotarla, por ejemplo con LIMIT.'],
    [500, { detail: 'x' }, {}, 'No se ha podido ejecutar la consulta.'],
  ])('error %i: mensaje legible', async (status, body, headers, message) => {
    mockSparql({
      sparql: () =>
        new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } }),
    })
    const { user } = await renderConsole()
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    expect(await within(resultsSection()).findByRole('alert')).toHaveTextContent(message)
  })

  it('si fallan las consultas guardadas lo dice, permite reintentar y deja usar el editor', async () => {
    let fail = true
    mockSparql({ queries: () => (fail ? jsonResponse({ detail: 'x' }, 503) : jsonResponse(REFERENCE)) })
    const { user } = renderApp('/sparql')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SPARQL_TEXT.queriesError)
    await user.type(editor(), 'SELECT libre')
    expect(editor()).toHaveValue('SELECT libre')

    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('button', { name: /Consulta de prueba A/ })).toBeInTheDocument()
  })

  it('QA-G4-04: conserva lo escrito antes de que carguen las consultas guardadas y lo ejecuta', async () => {
    let resolveQueries: (response: Response) => void = () => {}
    const fetchMock = mockSparql({
      queries: () => new Promise<Response>((resolve) => (resolveQueries = resolve)),
    })
    const { user } = renderApp('/sparql')
    await screen.findByText(SPARQL_TEXT.queriesLoading)
    const mine = 'ASK { ?s ?p ?o } # escrita antes de cargar'
    await user.click(editor())
    await user.paste(mine)

    resolveQueries(jsonResponse(REFERENCE))
    const first = await screen.findByRole('button', { name: /Consulta de prueba A/ })
    expect(editor()).toHaveValue(mine)
    expect(first).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => new URL(String(u)).pathname === '/sparql')).toBe(true),
    )
    const call = fetchMock.mock.calls.find(([u]) => new URL(String(u)).pathname === '/sparql')!
    expect(call[1]?.body).toBe(mine)

    // Elegir una consulta explícitamente sí carga su texto.
    await user.click(first)
    expect(editor()).toHaveValue('SELECT ?a WHERE { ?a ?b ?c }')
  })

  it('con sesión: pide las personales con el JWT, las pone tras las de referencia y guarda una nueva', async () => {
    let created: SavedQuery | null = null
    const fetchMock = mockSparql({
      queries: (_url, init) => {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { title: string; hint: string | null; query: string }
          created = { ...PERSONAL, id: '00000000-0000-4000-8000-000000000002', title: body.title, hint: body.hint, query: body.query }
          return jsonResponse(created, 201)
        }
        const auth = new Headers(init?.headers).get('Authorization')
        if (!auth) return jsonResponse(REFERENCE)
        // La API manda las de referencia primero; aquí se desordenan para comprobar que la consola las ordena.
        return jsonResponse([PERSONAL, ...REFERENCE, ...(created ? [created] : [])])
      },
      extra: {
        '/auth/token': () => jsonResponse(tokenFixture({ access_token: 'token-x' })),
        '/auth/me': () => jsonResponse(userFixture()),
      },
    })
    const { user } = await renderConsole()
    await login(user)
    await user.click(screen.getByRole('link', { name: 'Consulta SPARQL' }))
    await screen.findByRole('button', { name: 'Consulta personal' })

    const saved = screen.getByRole('region', { name: 'Consultas guardadas' })
    expect(within(saved).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Consulta de prueba APista de prueba A',
      'Consulta de prueba B',
      'Consulta personal',
    ])

    await user.clear(editor())
    await user.type(editor(), 'SELECT nueva')
    const save = screen.getByRole('button', { name: 'Guardar' })
    await user.click(save)
    expect(save).toHaveAttribute('aria-expanded', 'true')
    const form = screen.getByRole('form', { name: 'Guardar consulta' })
    expect(within(form).getByLabelText('Título')).toHaveFocus()

    await user.click(within(form).getByRole('button', { name: 'Guardar consulta' }))
    expect(within(form).getByRole('alert')).toHaveTextContent('Escribe un título.')

    await user.type(within(form).getByLabelText('Título'), 'Mi consulta')
    await user.type(within(form).getByLabelText('Pista (opcional)'), 'Mi pista')
    await user.click(within(form).getByRole('button', { name: 'Guardar consulta' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Consulta guardada.')
    expect(screen.queryByRole('form', { name: 'Guardar consulta' })).not.toBeInTheDocument()
    expect(save).toHaveFocus()
    const mine = await screen.findByRole('button', { name: 'Mi consultaMi pista' })
    await waitFor(() => expect(mine).toHaveAttribute('aria-pressed', 'true'))
    expect(editor()).toHaveValue('SELECT nueva')

    const post = fetchMock.mock.calls.find(([u, init]) => new URL(String(u)).pathname === '/sparql/queries' && init?.method === 'POST')!
    expect(JSON.parse(String(post[1]?.body))).toEqual({ title: 'Mi consulta', hint: 'Mi pista', query: 'SELECT nueva' })
    expect(new Headers(post[1]?.headers).get('Authorization')).toBe('Bearer token-x')

    // Con sesión, la ejecución lleva el JWT (límite de usuario autenticado).
    await user.click(screen.getByRole('button', { name: 'Ejecutar' }))
    await within(resultsSection()).findByRole('table')
    const run = fetchMock.mock.calls.find(([u]) => new URL(String(u)).pathname === '/sparql')!
    expect(new Headers(run[1]?.headers).get('Authorization')).toBe('Bearer token-x')
  })

  it.each([
    [409, 'Has llegado al máximo de consultas guardadas.'],
    [401, 'La sesión ha caducado. Inicia sesión de nuevo para guardar.'],
    [422, 'Revisa el título (hasta 120 caracteres), la pista (hasta 200) y la consulta.'],
  ])('al guardar, un %i se explica', async (status, message) => {
    mockSparql({
      queries: (_url, init) => (init?.method === 'POST' ? jsonResponse({ detail: 'x' }, status) : jsonResponse(REFERENCE)),
      extra: {
        '/auth/token': () => jsonResponse(tokenFixture()),
        '/auth/me': () => jsonResponse(userFixture()),
      },
    })
    const { user } = await renderConsole()
    await login(user)
    await user.click(screen.getByRole('link', { name: 'Consulta SPARQL' }))
    await screen.findByRole('button', { name: /Consulta de prueba A/ })
    await user.click(screen.getByRole('button', { name: 'Guardar' }))
    const form = screen.getByRole('form', { name: 'Guardar consulta' })
    await user.type(within(form).getByLabelText('Título'), 'Título')
    await user.click(within(form).getByRole('button', { name: 'Guardar consulta' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(message)
  })

  it('«Cancelar» y Escape cierran el formulario y devuelven el foco a «Guardar»', async () => {
    mockSparql({
      extra: {
        '/auth/token': () => jsonResponse(tokenFixture()),
        '/auth/me': () => jsonResponse(userFixture()),
      },
    })
    const { user } = await renderConsole()
    await login(user)
    await user.click(screen.getByRole('link', { name: 'Consulta SPARQL' }))
    await screen.findByRole('button', { name: /Consulta de prueba A/ })
    const save = screen.getByRole('button', { name: 'Guardar' })

    await user.click(save)
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('form', { name: 'Guardar consulta' })).not.toBeInTheDocument()
    expect(save).toHaveFocus()

    await user.click(save)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('form', { name: 'Guardar consulta' })).not.toBeInTheDocument()
    expect(save).toHaveFocus()
  })
})
