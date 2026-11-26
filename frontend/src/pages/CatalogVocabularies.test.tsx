import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { PublishMenu } from '../components/PublishMenu'
import { CRUD_TEXT } from '../crud/errors'
import { catalogDetailFixture, catalogSummaryFixture, pageFixture } from '../test/fixtures'
import { authRoutes, jsonResponse, mockFetch, renderApp, renderLoggedIn } from '../test/utils'
import { catalogRefFixture, vocabCardFixture, vocabPageFixture } from '../test/vocabFixtures'

const BASE = 'http://uri.test/itot/'

function LocationProbe() {
  const { search } = useLocation()
  return <span data-testid="search">{search}</span>
}

describe('Ficha de catálogo · esquemas y ontologías (decisión 50)', () => {
  const detail = catalogDetailFixture({
    scheme_count: 2,
    ontology_count: 1,
    schemes: [
      { slug: 'esq-prueba', corp: false, uri: `${BASE}vocab/esq-prueba`, title: 'Esquema de prueba' },
      { slug: 'corp-prueba', corp: true, uri: `${BASE}vocab/corp/corp-prueba`, title: null },
    ],
    ontologies: [{ slug: 'onto-prueba', uri: `${BASE}onto/onto-prueba`, title: 'Ontología de prueba' }],
  })

  function mock(extra: Parameters<typeof mockFetch>[0] = {}) {
    return mockFetch({
      '/catalogs/catalogo-prueba': () => jsonResponse(detail),
      '/datasets': () => jsonResponse(pageFixture([], { page_size: 20 })),
      ...extra,
    })
  }

  it('lista los vocabularios SKOS y las ontologías del catálogo con enlace a su ficha', async () => {
    mock()
    renderApp('/catalogos/catalogo-prueba')
    const schemes = await screen.findByRole('list', { name: 'Vocabularios SKOS del catálogo' })
    expect(within(schemes).getByRole('link', { name: /Esquema de prueba/ })).toHaveAttribute('href', '/vocabularios/esq-prueba')
    expect(within(schemes).getByRole('link', { name: /corp-prueba/ })).toHaveAttribute('href', '/vocabularios/corp/corp-prueba')
    expect(screen.getByText('2 vocabularios')).toBeInTheDocument()
    const ontologies = screen.getByRole('list', { name: 'Ontologías del catálogo' })
    expect(within(ontologies).getByRole('link', { name: /Ontología de prueba/ })).toHaveAttribute('href', '/ontologias/onto-prueba')
    expect(screen.getByText('1 ontología')).toBeInTheDocument()
  })

  it('catálogo sin esquemas ni ontologías (respuesta sin los campos nuevos): lo dice', async () => {
    mockFetch({
      '/catalogs/catalogo-prueba': () => jsonResponse(catalogDetailFixture()),
      '/datasets': () => jsonResponse(pageFixture([], { page_size: 20 })),
    })
    renderApp('/catalogos/catalogo-prueba')
    expect(await screen.findByText('Este catálogo no tiene vocabularios SKOS.')).toBeInTheDocument()
    expect(screen.getByText('Este catálogo no tiene ontologías.')).toBeInTheDocument()
    expect(screen.getByText('0 vocabularios')).toBeInTheDocument()
  })

  it('409 catalog_not_empty con esquemas y ontologías: los lista con enlace', async () => {
    const conflict = {
      detail: 'x',
      kind: 'catalog_not_empty',
      datasets: [],
      resources: [`${BASE}vocab/esq-prueba`, `${BASE}onto/onto-prueba`],
    }
    mock({
      ...authRoutes('editor'),
      '/catalogs/catalogo-prueba': (_u, init) => (init?.method === 'DELETE' ? jsonResponse(conflict, 409) : jsonResponse(detail)),
    })
    const { user } = await renderLoggedIn('/catalogos/catalogo-prueba')
    await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })
    await user.click(screen.getByRole('button', { name: 'Dar de baja' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('datasets, vocabularios y ontologías')
    await user.click(within(dialog).getByRole('button', { name: 'Dar de baja' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(CRUD_TEXT.catalogHasDatasets)
    const list = within(alert).getByRole('list', { name: 'Vocabularios y ontologías que siguen en el catálogo' })
    expect(within(list).getByRole('link', { name: 'vocab/esq-prueba' })).toHaveAttribute('href', '/vocabularios/esq-prueba')
    expect(within(list).getByRole('link', { name: 'onto/onto-prueba' })).toHaveAttribute('href', '/ontologias/onto-prueba')
    expect(within(alert).queryByRole('list', { name: 'Datasets que siguen en el catálogo' })).not.toBeInTheDocument()
  })
})

describe('Catálogos · recuentos (decisión 50)', () => {
  it('la tarjeta muestra datasets, vocabularios y ontologías (estos dos solo si hay)', async () => {
    mockFetch({
      '/catalogs': () =>
        jsonResponse({
          items: [
            catalogSummaryFixture({ scheme_count: 9, ontology_count: 3 }),
            catalogSummaryFixture({ slug: 'otro', title: 'Otro', dataset_count: 2, scheme_count: 0 }),
          ],
          total: 2,
        }),
    })
    renderApp('/catalogos')
    const first = (await screen.findByRole('link', { name: 'Catálogo de prueba' })).closest('article') as HTMLElement
    expect(within(first).getByText('1 dataset')).toBeInTheDocument()
    expect(within(first).getByText('9 vocabularios')).toBeInTheDocument()
    expect(within(first).getByText('3 ontologías')).toBeInTheDocument()
    const second = screen.getByRole('link', { name: 'Otro' }).closest('article') as HTMLElement
    expect(within(second).getByText('2 datasets')).toBeInTheDocument()
    expect(within(second).queryByText(/vocabulario/)).not.toBeInTheDocument()
  })
})

describe('Vocabularios · filtro ?catalog= y catálogo de las tarjetas (decisión 50)', () => {
  function mock() {
    return mockFetch({
      '/vocabularies': () =>
        jsonResponse(vocabPageFixture([vocabCardFixture({ catalog: catalogRefFixture() }), vocabCardFixture({ kind: 'external', slug: null, uri: 'https://externa.test/o/', title: 'Externa', catalog: null })])),
      '/catalogs': () => jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
    })
  }

  function vocabUrls(fetchMock: ReturnType<typeof mockFetch>) {
    return fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === '/vocabularies')
  }

  it('la tarjeta enlaza a su catálogo; las externas no tienen', async () => {
    mock()
    renderApp('/vocabularios')
    const card = (await screen.findByRole('link', { name: 'Ontología de prueba' })).closest('article') as HTMLElement
    expect(within(card).getByRole('link', { name: 'Catálogo de prueba' })).toHaveAttribute('href', '/catalogos/catalogo-prueba')
    const external = screen.getByText('Externa').closest('article') as HTMLElement
    expect(within(external).queryByText(/Catálogo:/)).not.toBeInTheDocument()
  })

  it('elegir un catálogo lanza ?catalog= y lo guarda en la URL; se lee de la URL', async () => {
    const fetchMock = mock()
    const { user } = renderApp('/vocabularios', <LocationProbe />)
    const select = await screen.findByLabelText('Catálogo')
    await user.selectOptions(select, 'catalogo-prueba')
    await waitFor(() => expect(vocabUrls(fetchMock).at(-1)!.searchParams.get('catalog')).toBe('catalogo-prueba'))
    expect(screen.getByTestId('search')).toHaveTextContent('?catalog=catalogo-prueba')
    await user.selectOptions(select, '')
    await waitFor(() => expect(vocabUrls(fetchMock).at(-1)!.searchParams.has('catalog')).toBe(false))
  })

  it('un ?catalog= que no es un slug se ignora', async () => {
    const fetchMock = mock()
    renderApp('/vocabularios?catalog=No%20V%C3%A1lido')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(vocabUrls(fetchMock)[0].searchParams.has('catalog')).toBe(false)
  })
})

describe('PublishMenu', () => {
  it('un clic fuera o Tab cierran el menú; elegir una opción lo cierra y avisa', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(
      <div>
        <PublishMenu label="Publicar recurso" items={[{ id: 'a', label: 'Opción A' }, { id: 'b', label: 'Opción B' }]} onSelect={onSelect} />
        <p>Fuera</p>
      </div>,
    )
    const button = screen.getByRole('button', { name: 'Publicar recurso' })
    await user.click(button)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByText('Fuera'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await user.click(button)
    await user.keyboard('{Tab}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    button.focus()
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Home}')
    expect(screen.getByRole('menuitem', { name: 'Opción A' })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'Opción B' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('b')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
