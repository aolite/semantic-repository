import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DatasetPage, VocabularyPage } from '../api'
import { cardFixture, pageFixture } from '../test/fixtures'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'
import { vocabCardsFixture, vocabPageFixture } from '../test/vocabFixtures'

function mockCatalog(
  respond: (url: URL) => DatasetPage | Response = () => pageFixture([cardFixture()]),
  vocab: (url: URL) => VocabularyPage | Response = () => vocabPageFixture([]),
) {
  return mockFetch({
    '/datasets': (url) => {
      const result = respond(new URL(url))
      return result instanceof Response ? result : jsonResponse(result)
    },
    '/vocabularies': (url) => {
      const result = vocab(new URL(url))
      return result instanceof Response ? result : jsonResponse(result)
    },
  })
}

function callsTo(fetchMock: ReturnType<typeof mockFetch>, path: string): URL[] {
  return fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === path)
}

function datasetsCalls(fetchMock: ReturnType<typeof mockFetch>): URL[] {
  return callsTo(fetchMock, '/datasets')
}

describe('Catálogo', () => {
  it('muestra la cabecera del prototipo', async () => {
    mockCatalog()
    renderApp('/')
    expect(screen.getByText('dcat:Catalog · itot-catalogo')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Datasets y vocabularios controlados' })).toBeInTheDocument()
    expect(screen.getByLabelText('Buscar en el catálogo')).toHaveAttribute('type', 'search')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
  })

  it('no muestra los botones sin funcionalidad todavía', async () => {
    mockCatalog()
    renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(screen.queryByRole('button', { name: 'Importar SKOS' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publicar recurso' })).not.toBeInTheDocument()
  })

  it('pinta la tarjeta con tipo, dominio, acceso, temas, formatos y versión, sin FAIR', async () => {
    mockCatalog()
    renderApp('/')
    const link = await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(link).toHaveAttribute('href', '/datasets/dataset-prueba')
    const card = link.closest('article')!
    expect(within(card).getByText('dcat:Dataset')).toBeInTheDocument()
    expect(within(card).getByText('OT / ICS')).toBeInTheDocument()
    expect(within(card).getByText('Restringido')).toBeInTheDocument()
    expect(within(card).getByText('Tema A')).toBeInTheDocument()
    expect(within(card).getByText('PCAP · CSV · Parquet · v2.1.0')).toBeInTheDocument()
    expect(within(card).queryByText(/FAIR/)).not.toBeInTheDocument()
    expect(within(card).queryByText('Dataset sintético')).not.toBeInTheDocument()
  })

  it('marca los datasets sintéticos', async () => {
    mockCatalog(() => pageFixture([cardFixture({ synthetic: true })]))
    renderApp('/')
    const card = (await screen.findByRole('link', { name: 'Dataset de prueba' })).closest('article')!
    expect(within(card).getByText('Dataset sintético')).toBeInTheDocument()
  })

  it('muestra el contador en singular y en plural a partir de total', async () => {
    mockCatalog(() => pageFixture([cardFixture()]))
    const first = renderApp('/')
    expect(await screen.findByText('1 recurso')).toBeInTheDocument()
    first.unmount()

    mockCatalog(() =>
      pageFixture([cardFixture(), cardFixture({ slug: 'otro', title: 'Otro de prueba' })], { total: 2 }),
    )
    renderApp('/')
    expect(await screen.findByText('2 recursos')).toBeInTheDocument()
  })

  it('filtra por dominio con aria-pressed y el slug en domain', async () => {
    const fetchMock = mockCatalog()
    const { user } = renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })

    const group = screen.getByRole('group', { name: 'Dominio' })
    const all = within(group).getByRole('button', { name: 'Todos los dominios' })
    expect(all).toHaveAttribute('aria-pressed', 'true')
    expect(datasetsCalls(fetchMock)[0].searchParams.has('domain')).toBe(false)

    for (const [label, slug] of [
      ['Seguridad IT', 'it'],
      ['OT / ICS', 'ot'],
      ['PQC e identidad', 'pqc'],
      ['IA adversaria', 'ia'],
    ]) {
      const chip = within(group).getByRole('button', { name: label })
      await user.click(chip)
      expect(chip).toHaveAttribute('aria-pressed', 'true')
      expect(all).toHaveAttribute('aria-pressed', 'false')
      await waitFor(() => expect(datasetsCalls(fetchMock).at(-1)!.searchParams.get('domain')).toBe(slug))
    }
  })

  it('lanza q con debounce al escribir', async () => {
    const fetchMock = mockCatalog()
    const { user } = renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })

    await user.type(screen.getByLabelText('Buscar en el catálogo'), 'modbus')
    await waitFor(() => expect(datasetsCalls(fetchMock).at(-1)!.searchParams.get('q')).toBe('modbus'))
    // Con debounce no se lanza una petición por pulsación.
    expect(datasetsCalls(fetchMock).length).toBeLessThan(4)
  })

  it('con «Vocabularios y ontologías» muestra las tarjetas de /vocabularies sin pedir datasets', async () => {
    const fetchMock = mockCatalog(undefined, () => vocabPageFixture())
    const { user } = renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    const before = datasetsCalls(fetchMock).length

    const group = screen.getByRole('group', { name: 'Tipo de recurso' })
    const vocab = within(group).getByRole('button', { name: 'Vocabularios y ontologías' })
    await user.click(vocab)

    expect(vocab).toHaveAttribute('aria-pressed', 'true')
    expect(within(group).getByRole('button', { name: 'Todo' })).toHaveAttribute('aria-pressed', 'false')
    const onto = await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(screen.queryByRole('link', { name: 'Dataset de prueba' })).not.toBeInTheDocument()
    expect(screen.getByText('4 recursos')).toBeInTheDocument()
    expect(datasetsCalls(fetchMock).length).toBe(before)

    // Tarjeta al estilo del catálogo: tipo RDF, tipo de vocabulario, estado, prefijo, métricas y versión.
    expect(onto).toHaveAttribute('href', '/ontologias/onto-prueba')
    const card = onto.closest('article')!
    expect(within(card).getByText('owl:Ontology')).toBeInTheDocument()
    expect(within(card).getByText('Ontología propia')).toBeInTheDocument()
    expect(within(card).getByText('Publicada')).toBeInTheDocument()
    expect(within(card).getByText('13 clases · 7 propiedades')).toBeInTheDocument()
    expect(within(card).getByText('v1.2.0')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Esquema de dominio de prueba' })).toHaveAttribute(
      'href',
      '/vocabularios/esq-prueba',
    )

    await user.click(within(group).getByRole('button', { name: 'Datasets' }))
    expect(await screen.findByRole('link', { name: 'Dataset de prueba' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Ontología de prueba' })).not.toBeInTheDocument()
  })

  it('«Todo» mezcla los datasets y los vocabularios, y pasa q a las dos rutas', async () => {
    const fetchMock = mockCatalog(undefined, () => vocabPageFixture(vocabCardsFixture().slice(0, 1)))
    const { user } = renderApp('/')

    const list = await screen.findByRole('list', { name: 'Recursos' })
    await within(list).findByRole('link', { name: 'Ontología de prueba' })
    const links = within(list)
      .getAllByRole('link')
      .map((l) => l.textContent)
    expect(links).toEqual(['Dataset de prueba', 'Ontología de prueba'])
    expect(screen.getByText('2 recursos')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Buscar en el catálogo'), 'prueba')
    await waitFor(() => expect(callsTo(fetchMock, '/vocabularies').at(-1)!.searchParams.get('q')).toBe('prueba'))
    expect(datasetsCalls(fetchMock).at(-1)!.searchParams.get('q')).toBe('prueba')
  })

  it('con un dominio elegido pide también los vocabularios con domain y los colorea', async () => {
    const fetchMock = mockCatalog(undefined, (url) =>
      vocabPageFixture(vocabCardsFixture().filter((c) => !url.searchParams.has('domain') || c.domain !== null)),
    )
    const { user } = renderApp('/')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(callsTo(fetchMock, '/vocabularies')[0].searchParams.has('domain')).toBe(false)

    await user.click(within(screen.getByRole('group', { name: 'Dominio' })).getByRole('button', { name: 'OT / ICS' }))
    await waitFor(() => expect(callsTo(fetchMock, '/vocabularies').at(-1)!.searchParams.get('domain')).toBe('ot'))
    expect(datasetsCalls(fetchMock).at(-1)!.searchParams.get('domain')).toBe('ot')
    expect(await screen.findByText('2 recursos')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Ontología de prueba' })).not.toBeInTheDocument()
    const scheme = screen.getByRole('link', { name: 'Esquema de dominio de prueba' }).closest('article')!
    expect(within(scheme).getByText('OT / ICS')).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('mantiene el placeholder del buscador (decisión abierta 30)', () => {
    mockCatalog()
    renderApp('/')
    expect(screen.getByLabelText('Buscar en el catálogo')).toHaveAttribute('placeholder', 'Título, concepto o URI')
  })

  it('muestra el estado de carga y después el vacío', async () => {
    mockCatalog(() => pageFixture([]))
    renderApp('/')
    expect(screen.getByRole('status')).toHaveTextContent('Cargando recursos…')
    expect(await screen.findByText('Ningún recurso coincide con los filtros.')).toBeInTheDocument()
    expect(screen.getByText('0 recursos')).toBeInTheDocument()
  })

  it('muestra un error accesible y permite reintentar', async () => {
    let fail = true
    mockCatalog(() => (fail ? jsonResponse({ detail: 'Service Unavailable' }, 503) : pageFixture([cardFixture()])))
    const { user } = renderApp('/')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se ha podido cargar el catálogo.')

    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('link', { name: 'Dataset de prueba' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('muestra el error si falla /vocabularies', async () => {
    mockCatalog(undefined, () => jsonResponse({ detail: 'Service Unavailable' }, 503))
    renderApp('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('No se ha podido cargar el catálogo.')
  })
})
