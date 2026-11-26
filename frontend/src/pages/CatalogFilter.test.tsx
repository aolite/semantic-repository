import { screen, waitFor } from '@testing-library/react'
import { useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'
import { cardFixture, catalogSummaryFixture, pageFixture } from '../test/fixtures'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'
import { vocabPageFixture } from '../test/vocabFixtures'

function mock(catalogs: Response = jsonResponse({ items: [catalogSummaryFixture()], total: 1 })) {
  return mockFetch({
    '/datasets': () => jsonResponse(pageFixture([cardFixture()])),
    '/vocabularies': () => jsonResponse(vocabPageFixture([])),
    '/catalogs': () => catalogs,
  })
}

function urls(fetchMock: ReturnType<typeof mockFetch>, path: string): URL[] {
  return fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === path)
}

function LocationProbe() {
  const { search } = useLocation()
  return <span data-testid="search">{search}</span>
}

describe('Catálogo · filtro por catálogo (decisiones 49 y 50)', () => {
  it('elegir un catálogo lanza ?catalog= en datasets y vocabularios, y lo guarda en la URL', async () => {
    const fetchMock = mock()
    const { user } = renderApp('/', <LocationProbe />)
    const select = await screen.findByLabelText('Catálogo')
    expect(select).toHaveValue('')
    expect(screen.getByRole('link', { name: 'Ver los catálogos' })).toHaveAttribute('href', '/catalogos')
    expect(urls(fetchMock, '/vocabularies').at(-1)!.searchParams.has('catalog')).toBe(false)

    await user.selectOptions(select, 'catalogo-prueba')
    await waitFor(() => expect(urls(fetchMock, '/datasets').at(-1)!.searchParams.get('catalog')).toBe('catalogo-prueba'))
    // Decisión 50: los esquemas y las ontologías propias también están en un catálogo.
    await waitFor(() => expect(urls(fetchMock, '/vocabularies').at(-1)!.searchParams.get('catalog')).toBe('catalogo-prueba'))
    expect(screen.getByTestId('search')).toHaveTextContent('?catalogo=catalogo-prueba')
  })

  it('lee el catálogo de la URL', async () => {
    const fetchMock = mock()
    renderApp('/?catalogo=catalogo-prueba')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(urls(fetchMock, '/datasets')[0].searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(urls(fetchMock, '/vocabularies')[0].searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(await screen.findByLabelText('Catálogo')).toHaveValue('catalogo-prueba')
  })

  it('si la lista de catálogos falla, no muestra el filtro y el catálogo sigue funcionando', async () => {
    mock(jsonResponse({ detail: 'x' }, 503))
    renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(screen.queryByLabelText('Catálogo')).not.toBeInTheDocument()
  })

  it('con «Vocabularios y ontologías» el filtro también se aplica (decisión 50)', async () => {
    const fetchMock = mock()
    renderApp('/?tipo=vocabularios&catalogo=catalogo-prueba')
    await screen.findByText('Ningún recurso coincide con los filtros.')
    expect(await screen.findByLabelText('Catálogo')).toHaveValue('catalogo-prueba')
    expect(urls(fetchMock, '/vocabularies')[0].searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(urls(fetchMock, '/datasets')).toHaveLength(0)
  })
})
