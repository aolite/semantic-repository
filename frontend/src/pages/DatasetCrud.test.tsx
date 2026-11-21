import { screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DatasetDetail, Role } from '../api'
import { INGEST_KIND_TEXT } from '../crud/errors'
import { VALIDATION_TEXT } from '../crud/validation'
import { catalogDetailFixture, catalogSummaryFixture, detailFixture, goneFixture, pageFixture, textResponse } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'

const PATH = '/datasets/dataset-prueba'
const CATALOG = { slug: 'catalogo-prueba', uri: 'http://uri.test/itot/catalogo/catalogo-prueba', title: 'Catálogo de prueba' }

type Handler = Parameters<typeof mockFetch>[0][string]

function withCatalog(overrides: Partial<DatasetDetail> = {}): DatasetDetail {
  return detailFixture({ catalog: CATALOG, ...overrides })
}

function mockDataset({ role, dataset, ingest }: { role?: Role; dataset?: Handler; ingest?: Handler } = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    [PATH]: dataset ?? (() => jsonResponse(withCatalog())),
    [`${PATH}/rdf`]: () => textResponse('# prueba', 'text/turtle'),
    '/catalogs': () =>
      jsonResponse({
        items: [catalogSummaryFixture(), catalogSummaryFixture({ slug: 'otro', uri: 'http://uri.test/itot/catalogo/otro', title: 'Otro catálogo' })],
        total: 2,
      }),
    '/catalogs/catalogo-prueba': () => jsonResponse(catalogDetailFixture()),
    '/datasets': (url, init) =>
      init?.method === 'POST' && ingest ? ingest(url, init) : jsonResponse(pageFixture([])),
  })
}

async function renderEditor(options: Parameters<typeof mockDataset>[0] = {}) {
  const fetchMock = mockDataset({ role: 'editor', ...options })
  const result = await renderLoggedIn(PATH)
  await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
  return { fetchMock, ...result }
}

const INGEST_RESULT = {
  slug: 'dataset-prueba',
  uri: 'http://uri.test/itot/dataset/dataset-prueba',
  graph: 'http://uri.test/itot/dataset/dataset-prueba',
  versions: ['2.1.0', '2.2.0'],
  triples: 10,
  created: false,
  changed: true,
}

describe('Ficha de dataset · catálogo y bajas (decisión 49)', () => {
  it('las migas enlazan el catálogo del dataset', async () => {
    mockDataset()
    renderApp(PATH)
    await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByRole('link', { name: 'Catálogo de prueba' })).toHaveAttribute('href', '/catalogos/catalogo-prueba')
  })

  it('410: ficha mínima con el título y la fecha de baja, sin error genérico', async () => {
    mockDataset({ dataset: () => jsonResponse(goneFixture(), 410) })
    renderApp(PATH)
    expect(await screen.findByRole('heading', { level: 1, name: 'Dataset dado de baja de prueba' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Dataset dado de baja' })).toBeInTheDocument()
    expect(screen.getByText('2000-01-02').closest('time')).toHaveAttribute('dateTime', '2000-01-02T03:04:05Z')
    expect(screen.getByText(/sus ficheros se han eliminado/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('Dataset no encontrado')).not.toBeInTheDocument()
  })

  it.each([undefined, 'miembro'] as const)('sin rol de edición (%s) no ve Editar, Nueva versión ni Dar de baja', async (role) => {
    mockDataset({ role })
    if (role) await renderLoggedIn(PATH)
    else renderApp(PATH)
    await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
    for (const name of ['Editar', 'Nueva versión', 'Dar de baja']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })

  it.each(['editor', 'admin'] as const)('%s ve las acciones', async (role) => {
    mockDataset({ role })
    await renderLoggedIn(PATH)
    const group = await screen.findByRole('group', { name: 'Acciones del dataset' })
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['Editar', 'Nueva versión', 'Dar de baja'])
  })

  it('editar: PATCH con los campos cambiados y el catálogo de destino (mover)', async () => {
    const { user, fetchMock } = await renderEditor({
      dataset: (_url, init) =>
        init?.method === 'PATCH' ? jsonResponse(withCatalog({ title: 'Título nuevo' })) : jsonResponse(withCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const region = screen.getByRole('region', { name: 'Editar dataset' })
    expect(within(region).getByLabelText('Título (en español)')).toHaveValue('Dataset de prueba')
    expect(within(region).getByLabelText('Publicador (opcional)')).toHaveAccessibleDescription('Déjalo vacío para no cambiarlo.')
    const select = await within(region).findByLabelText('Catálogo')
    expect(select).toHaveValue('catalogo-prueba')
    await user.selectOptions(select, 'otro')
    await user.type(within(region).getByLabelText('Título (en español)'), ' 2')
    await user.click(within(region).getByRole('button', { name: 'Guardar cambios' }))

    expect(await screen.findByText('Cambios guardados. El dataset se ha movido de catálogo.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'PATCH', PATH)).toEqual({ title: 'Dataset de prueba 2', catalog: 'otro' })
  })

  it('editar: 422 de catálogo de destino inexistente marca el catálogo', async () => {
    const body = { detail: 'No existe', kind: 'catalog', issues: [], report: null }
    const { user } = await renderEditor({
      dataset: (_url, init) => (init?.method === 'PATCH' ? jsonResponse(body, 422) : jsonResponse(withCatalog())),
    })
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const select = await screen.findByLabelText('Catálogo')
    await user.selectOptions(select, 'otro')
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(INGEST_KIND_TEXT.catalog)
    expect(select).toHaveAttribute('aria-invalid', 'true')
  })

  it('editar: título vacío no se manda', async () => {
    const { user, fetchMock } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    await user.clear(screen.getByLabelText('Título (en español)'))
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }))
    expect(screen.getByLabelText('Título (en español)')).toHaveAttribute('aria-invalid', 'true')
    expect(callsTo(fetchMock, 'PATCH', PATH)).toHaveLength(0)
  })

  it('«Nueva versión» sube el Turtle a POST /datasets?catalog= y recarga la ficha', async () => {
    const { user, fetchMock } = await renderEditor({ ingest: () => jsonResponse(INGEST_RESULT) })
    await user.click(screen.getByRole('button', { name: 'Nueva versión' }))
    const region = screen.getByRole('region', { name: 'Nueva versión' })
    expect(region).toHaveTextContent('todas las versiones ya publicadas sin cambios')
    expect(region).toHaveTextContent('Catálogo: Catálogo de prueba')
    const input = within(region).getByLabelText('Fichero RDF (Turtle o JSON-LD)')
    expect(input).toHaveFocus()
    const file = new File(['@prefix dcat: <http://www.w3.org/ns/dcat#> .'], 'serie.ttl', { type: 'text/turtle' })
    await user.upload(input, file)
    const before = callsTo(fetchMock, 'GET', PATH).length
    await user.click(within(region).getByRole('button', { name: 'Publicar versión' }))

    expect(await screen.findByText('RDF publicado. Versiones de la serie: 2.1.0, 2.2.0.')).toBeInTheDocument()
    const [url, init] = callsTo(fetchMock, 'POST', '/datasets')[0]
    expect(new URL(String(url)).searchParams.get('catalog')).toBe('catalogo-prueba')
    expect((init?.headers as Record<string, string>)['Content-Type']).toBe('text/turtle')
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer token-de-prueba')
    expect(init?.body).toBe(file)
    expect(callsTo(fetchMock, 'GET', PATH).length).toBeGreaterThan(before)
  })

  it('«Nueva versión» sin fichero válido no llama a la API', async () => {
    const { user, fetchMock } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Nueva versión' }))
    await user.click(screen.getByRole('button', { name: 'Publicar versión' }))
    expect(screen.getByRole('alert')).toHaveTextContent(VALIDATION_TEXT.file)
    expect(callsTo(fetchMock, 'POST', '/datasets')).toHaveLength(0)
  })

  it.each([
    ['version_removed', 409],
    ['version_immutable', 409],
    ['catalog_conflict', 409],
    ['withdrawn', 409],
    ['shacl', 422],
  ] as const)('«Nueva versión» explica el error %s (%i) con sus incidencias', async (kind, status) => {
    const body = {
      detail: 'detalle',
      kind,
      issues: [{ message: 'Incidencia de prueba', focus_node: 'http://uri.test/itot/dataset/dataset-prueba/2.1.0', path: null, value: null, severity: 'Violation', source_shape: null }],
      report: null,
    }
    const { user } = await renderEditor({ ingest: () => jsonResponse(body, status) })
    await user.click(screen.getByRole('button', { name: 'Nueva versión' }))
    await user.upload(screen.getByLabelText('Fichero RDF (Turtle o JSON-LD)'), new File(['x'], 'serie.jsonld', { type: 'application/ld+json' }))
    await user.click(screen.getByRole('button', { name: 'Publicar versión' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(INGEST_KIND_TEXT[kind])
    expect(alert).toHaveTextContent('Incidencia de prueba (2.1.0)')
  })

  it('dar de baja: confirmación propia que avisa de que se eliminan los ficheros; luego vuelve al catálogo', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const { user, fetchMock } = await renderEditor({
      dataset: (_url, init) => (init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(withCatalog())),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja el dataset' })
    expect(dialog).toHaveTextContent('Se eliminarán los ficheros de todas sus distribuciones.')
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })).toBeInTheDocument()
    expect(screen.getByText('Dataset «Dataset de prueba» dado de baja.')).toBeInTheDocument()
    expect(callsTo(fetchMock, 'DELETE', PATH)).toHaveLength(1)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('dar de baja: un 403 se explica dentro del diálogo', async () => {
    const { user } = await renderEditor({
      dataset: (_url, init) => (init?.method === 'DELETE' ? jsonResponse({ detail: 'x' }, 403) : jsonResponse(withCatalog())),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('hace falta el rol editor o admin')
  })
})
