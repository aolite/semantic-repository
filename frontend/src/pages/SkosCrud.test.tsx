import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ConceptNode, Role, SchemeDetail } from '../api'
import { CRUD_TEXT, INGEST_KIND_TEXT } from '../crud/errors'
import { catalogDetailFixture, catalogSummaryFixture, goneFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'
import {
  catalogRefFixture,
  conceptFixture,
  schemeFixture,
  schemeIngestFixture,
  treeFixture,
  vocabPageFixture,
} from '../test/vocabFixtures'

const PATH = '/schemes/esq-prueba'
const ROUTE = '/vocabularios/esq-prueba'
const BASE = 'http://uri.test/itot/'

type Handler = Parameters<typeof mockFetch>[0][string]

function inCatalog(overrides: Partial<SchemeDetail> = {}): SchemeDetail {
  return schemeFixture({ catalog: catalogRefFixture(), metadata: { creators: [], publisher: { uri: null, label: 'Publicador de prueba' }, license: null, issued: null, modified: null }, ...overrides })
}

function mockScheme({ role, scheme, extra = {} }: { role?: Role; scheme?: Handler; extra?: Record<string, Handler> } = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    '/vocabularies': () => jsonResponse(vocabPageFixture()),
    '/catalogs': () =>
      jsonResponse({ items: [catalogSummaryFixture(), catalogSummaryFixture({ slug: 'otro', title: 'Otro catálogo' })], total: 2 }),
    [PATH]: scheme ?? (() => jsonResponse(inCatalog())),
    [`${PATH}/concepts/grupo-a`]: () => jsonResponse(conceptFixture({ slug: 'grupo-a', pref_label: 'Grupo A' })),
    ...extra,
  })
}

async function renderEditor(options: Parameters<typeof mockScheme>[0] = {}) {
  const fetchMock = mockScheme({ role: 'editor', ...options })
  const result = await renderLoggedIn(ROUTE)
  await screen.findByRole('heading', { level: 1, name: 'Esquema de dominio de prueba' })
  return { fetchMock, ...result }
}

describe('Navegador SKOS · catálogo, conceptos retirados y 410 (decisión 50)', () => {
  it('muestra el catálogo del esquema con enlace a su ficha', async () => {
    mockScheme()
    renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Esquema de dominio de prueba' })
    expect(screen.getByRole('link', { name: 'Catálogo de prueba' })).toHaveAttribute('href', '/catalogos/catalogo-prueba')
  })

  it('marca los conceptos retirados en el árbol y en la ficha, con sus sustitutos', async () => {
    const tree: ConceptNode[] = treeFixture()
    tree[0].children[0].deprecated = true
    mockScheme({
      scheme: () => jsonResponse(inCatalog({ tree })),
      extra: {
        [`${PATH}/concepts/concepto-a1`]: () =>
          jsonResponse(
            conceptFixture({
              deprecated: true,
              replaced_by: [{ uri: `${BASE}vocab/esq-prueba/concepto-b1`, label: 'Concepto B1', scheme: `${BASE}vocab/esq-prueba` }],
            }),
          ),
      },
    })
    const { user } = renderApp(`${ROUTE}?concepto=concepto-a1`)
    const item = await screen.findByRole('treeitem', { name: 'Concepto A1 (retirado)' })
    expect(within(item).getByText('Retirado')).toBeInTheDocument()
    const note = await screen.findByRole('note', { name: 'Concepto retirado' })
    expect(within(note).getByText('dct:isReplacedBy')).toBeInTheDocument()
    const replacement = within(note).getByRole('link', { name: 'Concepto B1' })
    expect(replacement).toHaveAttribute('href', '/vocabularios/esq-prueba?concepto=concepto-b1')
    await user.click(replacement)
    expect(screen.getByRole('treeitem', { name: 'Concepto B1' })).toHaveAttribute('aria-selected', 'true')
  })

  it('un concepto retirado sin sustitutos lo dice; uno vivo no muestra el aviso', async () => {
    mockScheme({
      extra: { [`${PATH}/concepts/concepto-a1`]: () => jsonResponse(conceptFixture({ deprecated: true, replaced_by: [] })) },
    })
    renderApp(`${ROUTE}?concepto=concepto-a1`)
    expect(await screen.findByText('No indica sustitutos.')).toBeInTheDocument()
  })

  it('410 del esquema: ficha mínima de la baja', async () => {
    mockScheme({
      scheme: () =>
        jsonResponse(goneFixture({ resource: 'scheme', uri: `${BASE}vocab/esq-prueba`, title: 'Esquema retirado' }), 410),
    })
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Esquema retirado' })).toBeInTheDocument()
    expect(screen.getByText('skos:ConceptScheme')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Esquema dado de baja' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a Vocabularios' })).toHaveAttribute('href', '/vocabularios')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('410 de un concepto (por arrastre del esquema): lo nombra en la ficha mínima', async () => {
    mockScheme({ scheme: () => jsonResponse(goneFixture({ resource: 'scheme', title: 'Esquema retirado' }), 410) })
    renderApp(`${ROUTE}?concepto=concepto-a1`)
    expect(await screen.findByText('El concepto «concepto-a1» pertenecía a este esquema y se dio de baja con él.')).toBeInTheDocument()
  })

  it('410 al pedir el concepto con el esquema ya cargado: «Concepto dado de baja»', async () => {
    mockScheme({
      extra: { [`${PATH}/concepts/concepto-a1`]: () => jsonResponse(goneFixture({ resource: 'scheme', title: 'Esquema X' }), 410) },
    })
    renderApp(`${ROUTE}?concepto=concepto-a1`)
    expect(await screen.findByRole('heading', { name: 'Concepto dado de baja' })).toBeInTheDocument()
    expect(screen.getByText('El concepto «concepto-a1» se dio de baja con su esquema «Esquema X».')).toBeInTheDocument()
  })
})

describe('Navegador SKOS · CRUD del esquema (decisión 50)', () => {
  it.each([undefined, 'miembro'] as const)('sin rol de edición (%s) no se ven las acciones', async (role) => {
    mockScheme({ role })
    if (role) await renderLoggedIn(ROUTE)
    else renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Esquema de dominio de prueba' })
    expect(screen.queryByRole('group', { name: 'Acciones del esquema' })).not.toBeInTheDocument()
  })

  it('un esquema auxiliar no tiene acciones ni para el admin', async () => {
    mockFetch({
      ...authRoutes('admin'),
      '/vocabularies': () => jsonResponse(vocabPageFixture()),
      '/schemes/dominio': () => jsonResponse(schemeFixture({ slug: 'dominio', kind: 'auxiliary', title: 'Dominios', catalog: null, tree: [] })),
    })
    await renderLoggedIn('/vocabularios/dominio')
    await screen.findByRole('heading', { level: 1, name: 'Dominios' })
    expect(screen.queryByRole('button', { name: 'Dar de baja' })).not.toBeInTheDocument()
  })

  it('el editor edita título y catálogo: PATCH solo con lo cambiado y aviso de traslado', async () => {
    const patched = vi.fn(() => jsonResponse(inCatalog()))
    const { user, fetchMock } = await renderEditor({
      scheme: (_u, init) => (init?.method === 'PATCH' ? patched() : jsonResponse(inCatalog())),
    })
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const form = screen.getByRole('region', { name: 'Editar esquema' })
    expect(within(form).getByText(/en español/, { selector: 'strong' })).toBeInTheDocument()
    const title = within(form).getByLabelText('Título (en español)')
    expect(title).toHaveValue('Esquema de dominio de prueba')
    expect(within(form).getByLabelText('Publicador (opcional)')).toHaveValue('Publicador de prueba')
    await user.clear(title)
    await user.type(title, 'Nuevo título')
    const select = await within(form).findByRole('option', { name: 'Otro catálogo' })
    await user.selectOptions(within(form).getByLabelText('Catálogo'), select)
    await user.click(within(form).getByRole('button', { name: 'Guardar cambios' }))
    expect(await screen.findByText('Cambios guardados. El esquema se ha movido de catálogo.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'PATCH', PATH)).toEqual({ title: 'Nuevo título', catalog: 'otro' })
    expect(screen.getByRole('button', { name: 'Editar' })).toHaveFocus()
  })

  it('un esquema sin descripción se puede editar sin añadirla', async () => {
    const { user, fetchMock } = await renderEditor({
      scheme: (_u, init) => (init?.method === 'PATCH' ? jsonResponse(inCatalog()) : jsonResponse(inCatalog({ description: null }))),
    })
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const form = screen.getByRole('region', { name: 'Editar esquema' })
    await user.type(within(form).getByLabelText('Título (en español)'), ' 2')
    await user.click(within(form).getByRole('button', { name: 'Guardar cambios' }))
    await screen.findByText('Cambios guardados.')
    expect(lastBody(fetchMock, 'PATCH', PATH)).toEqual({ title: 'Esquema de dominio de prueba 2' })
  })

  it('error de la edición: 422 replacement y 403 not_managed', async () => {
    const { user } = await renderEditor({
      scheme: (_u, init) =>
        init?.method === 'PATCH' ? jsonResponse({ detail: 'x', kind: 'not_managed' }, 403) : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Editar' }))
    const form = screen.getByRole('region', { name: 'Editar esquema' })
    await user.type(within(form).getByLabelText('Título (en español)'), ' 2')
    await user.click(within(form).getByRole('button', { name: 'Guardar cambios' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(CRUD_TEXT.notManaged)
  })

  it('republicar: sube el fichero con el catálogo del esquema y avisa', async () => {
    const { user, fetchMock } = await renderEditor({
      extra: { '/schemes': () => jsonResponse(schemeIngestFixture({ created: false, concepts: 7 })) },
    })
    await user.click(screen.getByRole('button', { name: 'Republicar' }))
    const form = screen.getByRole('region', { name: 'Republicar el esquema' })
    expect(within(form).getByText('Catálogo de prueba')).toBeInTheDocument()
    expect(within(form).queryByLabelText('Catálogo')).not.toBeInTheDocument()
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), new File(['x'], 'e.ttl'))
    await user.click(within(form).getByRole('button', { name: 'Republicar esquema' }))
    expect(await screen.findByText('Esquema republicado con 7 conceptos.')).toBeInTheDocument()
    const [call] = callsTo(fetchMock, 'POST', '/schemes')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(screen.getByRole('button', { name: 'Republicar' })).toHaveFocus()
  })

  it('republicar sin conceptos ya publicados: 409 concepts_removed con la lista', async () => {
    const { user } = await renderEditor({
      extra: {
        '/schemes': () =>
          jsonResponse(
          {
            detail: 'x',
            kind: 'concepts_removed',
            issues: [{ message: 'Concepto publicado ausente', focus_node: `${BASE}vocab/esq-prueba/concepto-a1`, path: null, value: null, severity: 'Violation', source_shape: null }],
            report: null,
          },
          409,
        ),
      },
    })
    await user.click(screen.getByRole('button', { name: 'Republicar' }))
    const form = screen.getByRole('region', { name: 'Republicar el esquema' })
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), new File(['x'], 'e.ttl'))
    await user.click(within(form).getByRole('button', { name: 'Republicar esquema' }))
    const alert = await within(form).findByRole('alert')
    expect(alert).toHaveTextContent(INGEST_KIND_TEXT.concepts_removed)
    expect(within(alert).getByText('Concepto publicado ausente (concepto-a1)')).toBeInTheDocument()
  })

  it('dar de baja: confirma, llama a DELETE y vuelve a la ficha del catálogo', async () => {
    const { user, fetchMock } = await renderEditor({
      scheme: (_u, init) => (init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(inCatalog())),
      extra: {
        '/catalogs/catalogo-prueba': () => jsonResponse(catalogDetailFixture()),
        '/datasets': () => jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }),
      },
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja el esquema' })
    expect(within(dialog).getByRole('button', { name: 'Cancelar' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    expect(await screen.findByText('Esquema «Esquema de dominio de prueba» dado de baja.')).toBeInTheDocument()
    expect(callsTo(fetchMock, 'DELETE', PATH)).toHaveLength(1)
    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })).toBeInTheDocument()
  })

  it('dar de baja un esquema en uso: 409 in_use con quién lo usa y enlaces', async () => {
    const usedBy = [
      { uri: `${BASE}dataset/dataset-prueba/2.1.0`, resource: 'dataset', via: 'http://www.w3.org/ns/dcat#theme', target: `${BASE}vocab/esq-prueba/concepto-a1` },
      { uri: `${BASE}onto/onto-prueba/1.2.0`, resource: 'ontology', via: 'dct:subject', target: `${BASE}vocab/esq-prueba` },
      { uri: `${BASE}vocab/otro/c-1`, resource: 'scheme', via: 'skos:exactMatch', target: `${BASE}vocab/esq-prueba/grupo-a` },
    ]
    const { user } = await renderEditor({
      scheme: (_u, init) =>
        init?.method === 'DELETE' ? jsonResponse({ detail: 'x', kind: 'in_use', used_by: usedBy }, 409) : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja el esquema' })
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(CRUD_TEXT.inUse)
    const list = within(alert).getByRole('list', { name: 'Recursos que lo usan' })
    expect(within(list).getByRole('link', { name: 'dataset/dataset-prueba/2.1.0' })).toHaveAttribute(
      'href',
      '/datasets/dataset-prueba?version=2.1.0',
    )
    expect(within(list).getByRole('link', { name: 'onto/onto-prueba/1.2.0' })).toHaveAttribute('href', '/ontologias/onto-prueba?version=1.2.0')
    expect(within(list).getByRole('link', { name: 'vocab/otro/c-1' })).toHaveAttribute('href', '/vocabularios/otro?concepto=c-1')
    expect(list).toHaveTextContent('dcat:theme')
    expect(list).toHaveTextContent('vocab/esq-prueba/concepto-a1')
    // El diálogo sigue abierto para poder cancelar.
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('dar de baja con el bloqueo ocupado (503 con Retry-After)', async () => {
    const { user } = await renderEditor({
      scheme: (_u, init) =>
        init?.method === 'DELETE'
          ? new Response(JSON.stringify({ detail: 'x' }), { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': '3' } })
          : jsonResponse(inCatalog()),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja el esquema' })
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(CRUD_TEXT.busy)
  })

  it('los corporativos usan la ruta /schemes/corp/{slug}', async () => {
    const corp = inCatalog({ slug: 'corp-prueba', corp: true, kind: 'skos_corp', title: 'Corporativo', tree: [] })
    const fetchMock = mockFetch({
      ...authRoutes('editor'),
      '/vocabularies': () => jsonResponse(vocabPageFixture()),
      '/catalogs': () => jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
      '/schemes/corp/corp-prueba': (_u, init) => (init?.method === 'DELETE' ? jsonResponse({ detail: 'x' }, 403) : jsonResponse(corp)),
    })
    const { user } = await renderLoggedIn('/vocabularios/corp/corp-prueba')
    await screen.findByRole('heading', { level: 1, name: 'Corporativo' })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Dar de baja' }))
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent(CRUD_TEXT.forbidden)
    expect(callsTo(fetchMock, 'DELETE', '/schemes/corp/corp-prueba')).toHaveLength(1)
  })
})
