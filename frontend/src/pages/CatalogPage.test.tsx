import { screen, waitFor, within } from '@testing-library/react'
import { useLocation, useNavigate } from 'react-router'
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

  it('pinta la tarjeta con tipo, dominio, acceso, temas, formatos y versión, sin FAIR si fair_total es null', async () => {
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

/** Muestra la URL actual y ofrece «atrás», como el navegador. */
function RouterProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output data-testid="url">{`${location.pathname}${location.search}`}</output>
      <button type="button" onClick={() => navigate(-1)}>
        Atrás de prueba
      </button>
    </>
  )
}

describe('Catálogo · URL y paginación (fase 4)', () => {
  it('pinta «FAIR {fair_total}» con su barra solo en los datasets que lo tienen', async () => {
    mockCatalog(() =>
      pageFixture([cardFixture({ fair_total: 37 }), cardFixture({ slug: 'otro', title: 'Otro de prueba' })], { total: 2 }),
    )
    renderApp('/')
    const card = (await screen.findByRole('link', { name: 'Dataset de prueba' })).closest('article')!
    const fair = within(card).getByText('FAIR 37')
    const bar = fair.nextElementSibling as HTMLElement
    expect(bar).toHaveAttribute('aria-hidden', 'true')
    expect(bar.firstElementChild).toHaveStyle({ width: '37%' })
    const other = screen.getByRole('link', { name: 'Otro de prueba' }).closest('article')!
    expect(within(other).queryByText(/FAIR/)).not.toBeInTheDocument()
  })

  it('lee q, dominio, tipo y página de un enlace compartido', async () => {
    const fetchMock = mockCatalog(() => pageFixture([cardFixture()], { total: 45, page: 2, page_size: 20 }))
    renderApp('/?q=modbus&dominio=ot&tipo=datasets&pagina=2')
    await screen.findByRole('link', { name: 'Dataset de prueba' })

    const call = datasetsCalls(fetchMock).at(-1)!
    expect(call.searchParams.get('q')).toBe('modbus')
    expect(call.searchParams.get('domain')).toBe('ot')
    expect(call.searchParams.get('page')).toBe('2')
    expect(call.searchParams.get('page_size')).toBe('20')
    expect(callsTo(fetchMock, '/vocabularies')).toHaveLength(0)

    expect(screen.getByLabelText('Buscar en el catálogo')).toHaveValue('modbus')
    expect(within(screen.getByRole('group', { name: 'Dominio' })).getByRole('button', { name: 'OT / ICS' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      within(screen.getByRole('group', { name: 'Tipo de recurso' })).getByRole('button', { name: 'Datasets' }),
    ).toHaveAttribute('aria-pressed', 'true')
  })

  it('ignora valores desconocidos en la URL', async () => {
    const fetchMock = mockCatalog()
    renderApp('/?dominio=xx&tipo=otro&pagina=-3')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    const call = datasetsCalls(fetchMock).at(-1)!
    expect(call.searchParams.has('domain')).toBe(false)
    expect(call.searchParams.get('page')).toBe('1')
    expect(callsTo(fetchMock, '/vocabularies')).toHaveLength(1)
  })

  it('pagina con enlaces Anterior/Siguiente que conservan los filtros', async () => {
    const fetchMock = mockCatalog((url) =>
      pageFixture([cardFixture({ title: `Página ${url.searchParams.get('page')}` })], {
        total: 45,
        page: Number(url.searchParams.get('page')),
        page_size: 20,
      }),
    )
    const { user } = renderApp('/?dominio=it&tipo=datasets', <RouterProbe />)
    await screen.findByRole('link', { name: 'Página 1' })

    const pager = screen.getByRole('navigation', { name: 'Paginación' })
    expect(within(pager).getByText('Página 1 de 3')).toBeInTheDocument()
    expect(within(pager).queryByRole('link', { name: 'Anterior' })).not.toBeInTheDocument()
    const next = within(pager).getByRole('link', { name: 'Siguiente' })
    expect(next).toHaveAttribute('href', '/?dominio=it&tipo=datasets&pagina=2')

    await user.click(next)
    await screen.findByRole('link', { name: 'Página 2' })
    expect(screen.getByTestId('url')).toHaveTextContent('/?dominio=it&tipo=datasets&pagina=2')
    expect(datasetsCalls(fetchMock).at(-1)!.searchParams.get('page')).toBe('2')
    expect(screen.getByRole('link', { name: 'Anterior' })).toHaveAttribute('href', '/?dominio=it&tipo=datasets')

    // El botón atrás vuelve a la página anterior.
    await user.click(screen.getByRole('button', { name: 'Atrás de prueba' }))
    await screen.findByRole('link', { name: 'Página 1' })
    expect(screen.getByTestId('url')).toHaveTextContent('/?dominio=it&tipo=datasets')
  })

  it('no muestra la paginación con una sola página', async () => {
    mockCatalog()
    renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(screen.queryByRole('navigation', { name: 'Paginación' })).not.toBeInTheDocument()
  })

  it('en «Todo», los vocabularios van tras la última página de datasets', async () => {
    mockCatalog(
      (url) =>
        pageFixture([cardFixture({ title: `Página ${url.searchParams.get('page')}` })], {
          total: 21,
          page: Number(url.searchParams.get('page')),
          page_size: 20,
        }),
      () => vocabPageFixture(vocabCardsFixture().slice(0, 1)),
    )
    const { user } = renderApp('/')
    await screen.findByRole('link', { name: 'Página 1' })
    expect(screen.queryByRole('link', { name: 'Ontología de prueba' })).not.toBeInTheDocument()
    expect(screen.getByText('22 recursos')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Siguiente' }))
    expect(await screen.findByRole('link', { name: 'Ontología de prueba' })).toBeInTheDocument()
  })

  it('los filtros escriben la URL, vuelven a la página 1 y se deshacen con atrás', async () => {
    mockCatalog()
    const { user } = renderApp('/?pagina=3', <RouterProbe />)
    await screen.findByRole('link', { name: 'Dataset de prueba' })

    await user.click(within(screen.getByRole('group', { name: 'Dominio' })).getByRole('button', { name: 'IA adversaria' }))
    expect(screen.getByTestId('url')).toHaveTextContent(/^\/\?dominio=ia$/)
    await user.click(
      within(screen.getByRole('group', { name: 'Tipo de recurso' })).getByRole('button', { name: 'Vocabularios y ontologías' }),
    )
    expect(screen.getByTestId('url')).toHaveTextContent('/?dominio=ia&tipo=vocabularios')

    await user.click(screen.getByRole('button', { name: 'Atrás de prueba' }))
    expect(screen.getByTestId('url')).toHaveTextContent(/^\/\?dominio=ia$/)
    expect(
      within(screen.getByRole('group', { name: 'Tipo de recurso' })).getByRole('button', { name: 'Todo' }),
    ).toHaveAttribute('aria-pressed', 'true')
  })

  it('la búsqueda llega a la URL con debounce, sin crear una entrada por pulsación, y el campo sigue a «atrás»', async () => {
    mockCatalog()
    const { user } = renderApp('/', <RouterProbe />)
    await screen.findByRole('link', { name: 'Dataset de prueba' })

    await user.click(within(screen.getByRole('group', { name: 'Dominio' })).getByRole('button', { name: 'OT / ICS' }))
    await user.type(screen.getByLabelText('Buscar en el catálogo'), 'modbus')
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent('/?dominio=ot&q=modbus'))

    // Atrás vuelve al estado anterior al filtro de dominio: la búsqueda sustituyó su entrada.
    await user.click(screen.getByRole('button', { name: 'Atrás de prueba' }))
    await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent(/^\/$/))
    expect(screen.getByLabelText('Buscar en el catálogo')).toHaveValue('')
  })
})
