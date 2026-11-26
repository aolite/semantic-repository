import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Role } from '../api'
import { CRUD_TEXT } from '../crud/errors'
import { cardFixture, catalogDetailFixture, catalogSummaryFixture, detailFixture, goneFixture, pageFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'

const PATH = '/catalogs/catalogo-prueba'
const ROUTE = '/catalogos/catalogo-prueba'

type Handler = Parameters<typeof mockFetch>[0][string]

function mockCatalog({ role, detail, extra = {} }: { role?: Role; detail?: Handler; extra?: Record<string, Handler> } = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    [PATH]: detail ?? (() => jsonResponse(catalogDetailFixture())),
    '/datasets': () => jsonResponse(pageFixture([cardFixture()], { page_size: 20 })),
    '/catalogs': () => jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
    ...extra,
  })
}

async function renderEditor(handlers: Parameters<typeof mockCatalog>[0] = {}) {
  const fetchMock = mockCatalog({ role: 'editor', ...handlers })
  const result = await renderLoggedIn(ROUTE)
  await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })
  return { fetchMock, ...result }
}

describe('Ficha de catálogo (/catalogos/:slug)', () => {
  it('muestra los metadatos y sus datasets con el filtro ?catalog=', async () => {
    const fetchMock = mockCatalog()
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })).toBeInTheDocument()
    expect(screen.getByText('Descripción del catálogo de prueba.')).toBeInTheDocument()
    expect(screen.getByText('http://uri.test/itot/catalogo/catalogo-prueba')).toBeInTheDocument()
    expect(screen.getByText('Publicador de prueba')).toBeInTheDocument()

    const list = await screen.findByRole('list', { name: 'Datasets del catálogo' })
    expect(within(list).getByRole('link', { name: 'Dataset de prueba' })).toHaveAttribute('href', '/datasets/dataset-prueba')
    expect(screen.getByText('1 dataset')).toBeInTheDocument()
    const call = callsTo(fetchMock, 'GET', '/datasets')[0]
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
  })

  it('catálogo sin datasets: lo dice', async () => {
    mockCatalog({ extra: { '/datasets': () => jsonResponse(pageFixture([])) } })
    renderApp(ROUTE)
    expect(await screen.findByText('Este catálogo todavía no tiene datasets.')).toBeInTheDocument()
  })

  it('410: muestra la ficha mínima con el título y la fecha de baja', async () => {
    mockCatalog({
      detail: () =>
        jsonResponse(goneFixture({ resource: 'catalog', uri: 'http://uri.test/itot/catalogo/catalogo-prueba', title: 'Catálogo retirado' }), 410),
    })
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo retirado' })).toBeInTheDocument()
    expect(screen.getByText('Dado de baja', { selector: '.tag' })).toBeInTheDocument()
    expect(screen.getByText('2000-01-02').closest('time')).toHaveAttribute('dateTime', '2000-01-02T03:04:05Z')
    expect(screen.getByText('dcat:Catalog')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('410 sin fecha: [FECHA]', async () => {
    mockCatalog({ detail: () => jsonResponse(goneFixture({ resource: 'catalog', withdrawn_at: null }), 410) })
    renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Dataset dado de baja de prueba' })
    expect(screen.getByText('[FECHA]')).toBeInTheDocument()
  })

  it('404: «Catálogo no encontrado»', async () => {
    mockCatalog({ detail: () => jsonResponse({ detail: 'No existe' }, 404) })
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo no encontrado' })).toBeInTheDocument()
  })

  it.each([undefined, 'miembro'] as const)('sin rol de edición (%s) no se ven las acciones', async (role) => {
    mockCatalog({ role })
    if (role) await renderLoggedIn(ROUTE)
    else renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })
    for (const name of ['Editar catálogo', 'Dar de baja', 'Importar SKOS', 'Publicar recurso']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })

  it('el editor edita el catálogo: PATCH solo con los campos cambiados', async () => {
    const patched = vi.fn(() => jsonResponse(catalogDetailFixture({ title: 'Título nuevo' })))
    const { user, fetchMock } = await renderEditor({
      detail: (_url, init) => (init?.method === 'PATCH' ? patched() : jsonResponse(catalogDetailFixture())),
    })
    await user.click(screen.getByRole('button', { name: 'Editar catálogo' }))
    expect(screen.getByRole('button', { name: 'Editar catálogo' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByLabelText('Slug')).not.toBeInTheDocument()
    const title = screen.getByLabelText('Título (en español)')
    expect(title).toHaveValue('Catálogo de prueba')
    expect(screen.getByLabelText('Publicador')).toHaveValue('Publicador de prueba')
    await user.clear(title)
    await user.type(title, 'Título nuevo')
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }))

    expect(await screen.findByText('Cambios guardados.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'PATCH', PATH)).toEqual({ title: 'Título nuevo' })
    expect(screen.getByRole('button', { name: 'Editar catálogo' })).toHaveFocus()
  })

  it('editar sin cambios no llama a la API', async () => {
    const { user, fetchMock } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Editar catálogo' }))
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }))
    expect(await screen.findByText('No había cambios que guardar.')).toBeInTheDocument()
    expect(callsTo(fetchMock, 'PATCH', PATH)).toHaveLength(0)
  })

  it('el editor crea un dataset en el catálogo y va a su ficha', async () => {
    const { user, fetchMock } = await renderEditor({
      extra: {
        [`${PATH}/datasets`]: () => jsonResponse(detailFixture({ slug: 'nuevo', title: 'Nuevo', version: null, versions: [], current_version: null }), 201),
        '/datasets/nuevo': () => jsonResponse(detailFixture({ slug: 'nuevo', title: 'Nuevo', version: null, versions: [], current_version: null })),
      },
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nuevo dataset' }))
    const form = screen.getByRole('region', { name: 'Nuevo dataset en este catálogo' })
    expect(form).toHaveTextContent('Catálogo: Catálogo de prueba')
    expect(within(form).queryByLabelText('Catálogo')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Slug'), 'nuevo')
    await user.type(screen.getByLabelText('Título (en español)'), 'Nuevo')
    await user.type(screen.getByLabelText('Descripción (en español)'), 'Descripción')
    expect(screen.getByLabelText('Publicador (opcional)')).not.toBeRequired()
    await user.click(screen.getByRole('button', { name: 'Crear dataset' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Nuevo' })).toBeInTheDocument()
    expect(screen.getByText(/Dataset creado/)).toBeInTheDocument()
    expect(lastBody(fetchMock, 'POST', `${PATH}/datasets`)).toEqual({
      slug: 'nuevo',
      title: 'Nuevo',
      description: 'Descripción',
      publisher_name: null,
    })
  })

  it('dar de baja pide confirmación propia; cancelar no llama a la API', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const { user, fetchMock } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog', { name: 'Dar de baja el catálogo' })
    expect(dialog).toHaveTextContent('Solo se puede dar de baja un catálogo vacío')
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(callsTo(fetchMock, 'DELETE', PATH)).toHaveLength(0)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('confirmar da de baja (DELETE) y vuelve a los catálogos con un aviso', async () => {
    const { user, fetchMock } = await renderEditor({
      detail: (_url, init) => (init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(catalogDetailFixture())),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Dar de baja' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogos' })).toBeInTheDocument()
    expect(screen.getByText('Catálogo «Catálogo de prueba» dado de baja.')).toBeInTheDocument()
    expect(callsTo(fetchMock, 'DELETE', PATH)).toHaveLength(1)
  })

  it('409 con datasets: lista los que hay que mover o dar de baja antes', async () => {
    const conflict = { detail: 'El catálogo tiene datasets', kind: 'catalog_not_empty', datasets: ['http://uri.test/itot/dataset/dataset-prueba'] }
    const { user } = await renderEditor({
      detail: (_url, init) => (init?.method === 'DELETE' ? jsonResponse(conflict, 409) : jsonResponse(catalogDetailFixture())),
    })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(CRUD_TEXT.catalogHasDatasets)
    const list = within(alert).getByRole('list', { name: 'Datasets que siguen en el catálogo' })
    expect(within(list).getByRole('link', { name: 'dataset-prueba' })).toHaveAttribute('href', '/datasets/dataset-prueba')
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Dar de baja' })).not.toHaveAttribute('aria-disabled'))
  })
})
