import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api'
import { CRUD_TEXT } from '../crud/errors'
import { catalogDetailFixture, catalogSummaryFixture, pageFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'

const LIST = {
  items: [
    catalogSummaryFixture(),
    catalogSummaryFixture({ slug: 'otro', uri: 'http://uri.test/itot/catalogo/otro', title: 'Otro catálogo', dataset_count: 0, publisher: null }),
  ],
  total: 2,
}

type Handler = Parameters<typeof mockFetch>[0][string]

function mockCatalogs(post?: Handler, role?: Role) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    '/catalogs': (url, init) => (init?.method === 'POST' && post ? post(url, init) : jsonResponse(LIST)),
    '/catalogs/nuevo-catalogo': () => jsonResponse(catalogDetailFixture({ slug: 'nuevo-catalogo', title: 'Nuevo', datasets: [], dataset_count: 0 })),
    '/datasets': () => jsonResponse(pageFixture([])),
  })
}

async function openForm(role: Role = 'editor', post?: Handler) {
  const fetchMock = mockCatalogs(post, role)
  const { user } = await renderLoggedIn('/catalogos')
  await user.click(await screen.findByRole('button', { name: 'Nuevo catálogo' }))
  const form = screen.getByRole('region', { name: 'Nuevo catálogo' })
  return { user, fetchMock, form }
}

async function fill(user: Awaited<ReturnType<typeof openForm>>['user'], slug = 'nuevo-catalogo') {
  if (slug) await user.type(screen.getByLabelText('Slug'), slug)
  await user.type(screen.getByLabelText('Título (en español)'), 'Título de prueba')
  await user.type(screen.getByLabelText('Descripción (en español)'), 'Descripción de prueba')
  await user.type(screen.getByLabelText('Publicador'), 'Publicador de prueba')
}

describe('Catálogos (/catalogos)', () => {
  it('lista los catálogos con su número de datasets y enlaza su ficha', async () => {
    mockCatalogs()
    renderApp('/catalogos')
    const list = await screen.findByRole('list', { name: 'Catálogos' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByRole('link', { name: 'Catálogo de prueba' })).toHaveAttribute('href', '/catalogos/catalogo-prueba')
    expect(items[0]).toHaveTextContent('1 dataset')
    expect(items[0]).toHaveTextContent('Publicador de prueba')
    expect(items[1]).toHaveTextContent('0 datasets')
    expect(screen.getByText('2 catálogos')).toBeInTheDocument()
    // La navegación marca «Catálogo» dentro de la sección.
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByRole('link', { name: 'Catálogo' })).toHaveAttribute('aria-current', 'true')
  })

  it('muestra el error con «Reintentar» si la API falla', async () => {
    mockFetch({ '/catalogs': () => jsonResponse({ detail: 'x' }, 503) })
    renderApp('/catalogos')
    expect(await screen.findByRole('alert')).toHaveTextContent('No se han podido cargar los catálogos.')
  })

  it('el anónimo no ve «Nuevo catálogo»', async () => {
    mockCatalogs()
    renderApp('/catalogos')
    await screen.findByRole('list', { name: 'Catálogos' })
    expect(screen.queryByRole('button', { name: 'Nuevo catálogo' })).not.toBeInTheDocument()
  })

  it('el miembro tampoco lo ve', async () => {
    mockCatalogs(undefined, 'miembro')
    await renderLoggedIn('/catalogos')
    await screen.findByRole('list', { name: 'Catálogos' })
    expect(screen.queryByRole('button', { name: 'Nuevo catálogo' })).not.toBeInTheDocument()
  })

  it.each(['editor', 'admin'] as const)('%s crea un catálogo con POST /catalogs y va a su ficha', async (role) => {
    const { user, fetchMock } = await openForm(role, () =>
      jsonResponse(catalogDetailFixture({ slug: 'nuevo-catalogo', title: 'Nuevo', datasets: [], dataset_count: 0 }), 201),
    )
    expect(screen.getByLabelText('Slug')).toHaveFocus()
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Nuevo' })).toBeInTheDocument()
    expect(screen.getByText('Catálogo creado.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'POST', '/catalogs')).toEqual({
      slug: 'nuevo-catalogo',
      title: 'Título de prueba',
      description: 'Descripción de prueba',
      publisher_name: 'Publicador de prueba',
    })
    const post = callsTo(fetchMock, 'POST', '/catalogs')[0]
    expect((post[1]?.headers as Record<string, string>).Authorization).toBe('Bearer token-de-prueba')
  })

  it('valida en el cliente los campos obligatorios y el slug, sin llamar a la API', async () => {
    const { user, fetchMock } = await openForm()
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Revisa los campos marcados.')
    expect(screen.getByLabelText('Slug')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Slug')).toHaveFocus()
    expect(screen.getByLabelText('Título (en español)')).toHaveAttribute('aria-invalid', 'true')

    await user.type(screen.getByLabelText('Slug'), 'Con Espacios')
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    expect(screen.getByLabelText('Slug')).toHaveAccessibleDescription(/Solo minúsculas sin acentos/)
    expect(callsTo(fetchMock, 'POST', '/catalogs')).toHaveLength(0)
  })

  it.each([
    ['slug_in_use', CRUD_TEXT.slugInUse],
    ['withdrawn', CRUD_TEXT.slugWithdrawn],
  ] as const)('409 %s: mensaje propio y slug marcado', async (kind, text) => {
    const { user } = await openForm('editor', () => jsonResponse({ detail: 'x', kind }, 409))
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
    expect(screen.getByLabelText('Slug')).toHaveAttribute('aria-invalid', 'true')
  })

  it('503 con Retry-After: el servidor está ocupado', async () => {
    const { user } = await openForm('editor', () =>
      new Response(JSON.stringify({ detail: 'x' }), { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': '5' } }),
    )
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(CRUD_TEXT.busy)
    // El formulario sigue abierto para reintentar.
    expect(screen.getByRole('button', { name: 'Crear catálogo' })).toBeEnabled()
  })

  it('422 SHACL: muestra el mensaje y las incidencias', async () => {
    const body = {
      detail: 'No cumple las formas',
      kind: 'shacl',
      issues: [{ message: 'Falta un valor', focus_node: null, path: 'http://purl.org/dc/terms/title', value: null, severity: 'Violation', source_shape: null }],
      report: null,
    }
    const { user } = await openForm('editor', () => jsonResponse(body, 422))
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Los datos no cumplen las reglas de validación (SHACL).')
    expect(within(alert).getByRole('listitem')).toHaveTextContent('Falta un valor (title)')
  })

  it('«Cancelar» y Escape cierran el formulario y devuelven el foco', async () => {
    const { user } = await openForm()
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('region', { name: 'Nuevo catálogo' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Nuevo catálogo' })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'Nuevo catálogo' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('region', { name: 'Nuevo catálogo' })).not.toBeInTheDocument()
  })
})
