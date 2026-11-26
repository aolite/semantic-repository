import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api'
import { CRUD_TEXT, INGEST_KIND_TEXT, ONTOLOGY_INGEST_TEXT } from '../crud/errors'
import { catalogDetailFixture, catalogSummaryFixture, goneFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'
import { catalogRefFixture, ontologyFixture, ontologyIngestFixture } from '../test/vocabFixtures'

const PATH = '/ontologies/onto-prueba'
const ROUTE = '/ontologias/onto-prueba'
const BASE = 'http://uri.test/itot/'

type Handler = Parameters<typeof mockFetch>[0][string]

const inCatalog = () => ontologyFixture({ catalog: catalogRefFixture() })

function mockOntology({ role, ontology, extra = {} }: { role?: Role; ontology?: Handler; extra?: Record<string, Handler> } = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    '/catalogs': () =>
      jsonResponse({ items: [catalogSummaryFixture(), catalogSummaryFixture({ slug: 'otro', title: 'Otro catálogo' })], total: 2 }),
    [PATH]: ontology ?? (() => jsonResponse(inCatalog())),
    ...extra,
  })
}

async function renderEditor(options: Parameters<typeof mockOntology>[0] = {}) {
  const fetchMock = mockOntology({ role: 'editor', ...options })
  const result = await renderLoggedIn(ROUTE)
  await screen.findByRole('heading', { level: 1, name: 'Ontología de prueba' })
  return { fetchMock, ...result }
}

describe('Ficha de ontología · catálogo y 410 (decisión 50)', () => {
  it('muestra su catálogo con enlace a la ficha', async () => {
    mockOntology()
    renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Ontología de prueba' })
    expect(screen.getByRole('link', { name: 'Catálogo de prueba' })).toHaveAttribute('href', '/catalogos/catalogo-prueba')
  })

  it('410 de la ontología: ficha mínima de la baja', async () => {
    mockOntology({
      ontology: () => jsonResponse(goneFixture({ resource: 'ontology', uri: `${BASE}onto/onto-prueba`, title: 'Ontología retirada' }), 410),
    })
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Ontología retirada' })).toBeInTheDocument()
    expect(screen.getByText('owl:Ontology')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ontología dada de baja' })).toBeInTheDocument()
    expect(screen.getByText('Dada de baja', { selector: '.tag' })).toBeInTheDocument()
  })

  it('410 de una versión (por arrastre): lo dice en la ficha mínima', async () => {
    mockOntology({ ontology: () => jsonResponse(goneFixture({ resource: 'ontology', title: 'Ontología retirada' }), 410) })
    renderApp(`${ROUTE}?version=1.0.0`)
    expect(await screen.findByText('La versión 1.0.0 se dio de baja con la ontología.')).toBeInTheDocument()
  })
})

describe('Ficha de ontología · CRUD (decisión 50)', () => {
  it.each([undefined, 'miembro'] as const)('sin rol de edición (%s) no se ven las acciones', async (role) => {
    mockOntology({ role })
    if (role) await renderLoggedIn(ROUTE)
    else renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Ontología de prueba' })
    expect(screen.queryByRole('group', { name: 'Acciones de la ontología' })).not.toBeInTheDocument()
  })

  it('mover de catálogo: PATCH con el destino; el mismo catálogo no se manda', async () => {
    const { user, fetchMock } = await renderEditor({
      ontology: (_u, init) =>
        init?.method === 'PATCH' ? jsonResponse(ontologyFixture({ catalog: catalogRefFixture({ slug: 'otro' }) })) : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Mover de catálogo' }))
    const form = screen.getByRole('region', { name: 'Mover la ontología de catálogo' })
    const select = within(form).getByLabelText('Catálogo de destino')
    await within(form).findByRole('option', { name: 'Otro catálogo' })
    expect(select).toHaveValue('catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Mover' }))
    expect(within(form).getByRole('alert')).toHaveTextContent('Elige un catálogo distinto del actual.')
    expect(callsTo(fetchMock, 'PATCH', PATH)).toHaveLength(0)

    await user.selectOptions(select, 'otro')
    await user.click(within(form).getByRole('button', { name: 'Mover' }))
    expect(await screen.findByText('La ontología se ha movido de catálogo.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'PATCH', PATH)).toEqual({ catalog: 'otro' })
    expect(screen.getByRole('button', { name: 'Mover de catálogo' })).toHaveFocus()
  })

  it('mover: 422 catalog (el destino no existe o se dio de baja) y 403 not_managed', async () => {
    let status = 422
    const { user } = await renderEditor({
      ontology: (_u, init) =>
        init?.method === 'PATCH'
          ? status === 422
            ? jsonResponse({ detail: 'x', kind: 'catalog', issues: [], report: null }, 422)
            : jsonResponse({ detail: 'x', kind: 'not_managed' }, 403)
          : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Mover de catálogo' }))
    const form = screen.getByRole('region', { name: 'Mover la ontología de catálogo' })
    await within(form).findByRole('option', { name: 'Otro catálogo' })
    await user.selectOptions(within(form).getByLabelText('Catálogo de destino'), 'otro')
    await user.click(within(form).getByRole('button', { name: 'Mover' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(INGEST_KIND_TEXT.catalog)
    expect(within(form).getByLabelText('Catálogo de destino')).toHaveAttribute('aria-invalid', 'true')
    status = 403
    await user.click(within(form).getByRole('button', { name: 'Mover' }))
    await waitFor(() => expect(within(form).getByRole('alert')).toHaveTextContent(CRUD_TEXT.notManaged))
  })

  it('nueva versión: sube el RDF con el catálogo de la ontología y vuelve a la versión actual', async () => {
    const { user, fetchMock } = await renderEditor({ extra: { '/ontologies': () => jsonResponse(ontologyIngestFixture(), 201) } })
    await user.click(screen.getByRole('button', { name: 'Nueva versión' }))
    const form = screen.getByRole('region', { name: 'Nueva versión de la ontología' })
    expect(within(form).getByText('Catálogo de prueba')).toBeInTheDocument()
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), new File(['x'], 'o.ttl'))
    await user.click(within(form).getByRole('button', { name: 'Publicar versión' }))
    expect(await screen.findByText('Versión 1.3.0 de la ontología publicada.')).toBeInTheDocument()
    const [call] = callsTo(fetchMock, 'POST', '/ontologies')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
  })

  it.each([
    ['version_immutable', 409, INGEST_KIND_TEXT.version_immutable],
    ['catalog_conflict', 409, ONTOLOGY_INGEST_TEXT.catalog_conflict!],
    ['withdrawn', 409, ONTOLOGY_INGEST_TEXT.withdrawn!],
    ['prefix_withdrawn', 409, INGEST_KIND_TEXT.prefix_withdrawn],
  ])('nueva versión con error %s (%i)', async (kind, status, message) => {
    const { user } = await renderEditor({
      extra: { '/ontologies': () => jsonResponse({ detail: 'x', kind, issues: [], report: null }, status) },
    })
    await user.click(screen.getByRole('button', { name: 'Nueva versión' }))
    const form = screen.getByRole('region', { name: 'Nueva versión de la ontología' })
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), new File(['x'], 'o.ttl'))
    await user.click(within(form).getByRole('button', { name: 'Publicar versión' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(message)
  })

  it('dar de baja: confirma y vuelve a la ficha del catálogo con el aviso', async () => {
    const { user, fetchMock } = await renderEditor({
      ontology: (_u, init) => (init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(inCatalog())),
      extra: {
        '/catalogs/catalogo-prueba': () => jsonResponse(catalogDetailFixture()),
        '/datasets': () => jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }),
      },
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja la ontología' })
    expect(dialog).toHaveTextContent('todas sus versiones')
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    expect(await screen.findByText('Ontología «Ontología de prueba» dada de baja.')).toBeInTheDocument()
    expect(callsTo(fetchMock, 'DELETE', PATH)).toHaveLength(1)
  })

  it('dar de baja una ontología importada por otra: 409 in_use (un término no tiene propiedad)', async () => {
    const usedBy = [
      { uri: `${BASE}onto/otra/1.0.0`, resource: 'ontology', via: 'http://www.w3.org/2002/07/owl#imports', target: `${BASE}onto/onto-prueba` },
      { uri: `${BASE}onto/otra/1.0.0`, resource: 'ontology', via: null, target: `${BASE}onto/onto-prueba#Clase` },
    ]
    const { user } = await renderEditor({
      ontology: (_u, init) =>
        init?.method === 'DELETE' ? jsonResponse({ detail: 'x', kind: 'in_use', used_by: usedBy }, 409) : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja la ontología' })
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(CRUD_TEXT.inUse)
    const list = within(alert).getByRole('list', { name: 'Recursos que lo usan' })
    expect(list).toHaveTextContent('owl:imports')
    expect(list).toHaveTextContent('usa el término')
    expect(list).toHaveTextContent('onto/onto-prueba#Clase')
    expect(within(list).getAllByRole('link', { name: 'onto/otra/1.0.0' })[0]).toHaveAttribute('href', '/ontologias/otra?version=1.0.0')
  })
})
