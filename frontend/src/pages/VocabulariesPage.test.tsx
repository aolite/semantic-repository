import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { VocabularyPage } from '../api'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'
import { vocabCardsFixture, vocabPageFixture } from '../test/vocabFixtures'

function mockVocab(respond: (url: URL) => VocabularyPage | Response = () => vocabPageFixture()) {
  return mockFetch({
    '/vocabularies': (url) => {
      const result = respond(new URL(url))
      return result instanceof Response ? result : jsonResponse(result)
    },
  })
}

function vocabCalls(fetchMock: ReturnType<typeof mockFetch>): URL[] {
  return fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === '/vocabularies')
}

function cardOf(name: string): HTMLElement {
  return screen.getByRole('link', { name }).closest('article') as HTMLElement
}

describe('Vocabularios y ontologías', () => {
  it('muestra la cabecera del prototipo sin los botones sin función', async () => {
    mockVocab()
    renderApp('/vocabularios')
    expect(screen.getByText('dcat:Catalog · itot-vocabularios')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Vocabularios y ontologías' })).toBeInTheDocument()
    expect(screen.getByLabelText('Buscar vocabulario')).toHaveAttribute(
      'placeholder',
      'Nombre, prefijo o espacio de nombres',
    )
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(screen.queryByRole('button', { name: 'Catalogar externa' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nuevo vocabulario' })).not.toBeInTheDocument()
  })

  it('muestra «Tipos de vocabulario» en la navegación lateral y marca Vocabularios', async () => {
    mockVocab()
    renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByRole('heading', { name: 'Tipos de vocabulario' })).toBeInTheDocument()
    expect(within(nav).queryByRole('heading', { name: 'Esquemas de conceptos' })).not.toBeInTheDocument()
    for (const label of ['Ontologías propias', 'Ontologías externas', 'SKOS corporativos', 'SKOS de dominio']) {
      expect(within(nav).getByText(label)).toBeInTheDocument()
    }
    expect(within(nav).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('aria-current', 'page')
  })

  it('pinta los recuentos de counts en las tarjetas de estadísticas', async () => {
    mockVocab()
    renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    const stats = screen.getByRole('group', { name: 'Recuento por tipo' })
    expect(within(stats).getByRole('button', { name: '3 Ontologías propias' })).toHaveAttribute('aria-pressed', 'false')
    expect(within(stats).getByRole('button', { name: '2 Ontologías externas' })).toBeInTheDocument()
    expect(within(stats).getByRole('button', { name: '4 SKOS corporativos' })).toBeInTheDocument()
    expect(within(stats).getByRole('button', { name: '5 SKOS de dominio' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Todos los vocabularios' })).toBeInTheDocument()
    expect(screen.getByText('4 vocabularios')).toBeInTheDocument()
  })

  it('filtra por tipo con los chips y con las estadísticas (aria-pressed y kind)', async () => {
    const fetchMock = mockVocab((url) => {
      const kind = url.searchParams.get('kind')
      const items = vocabCardsFixture().filter((c) => !kind || c.kind === kind)
      return vocabPageFixture(items)
    })
    const { user } = renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(vocabCalls(fetchMock)[0].searchParams.has('kind')).toBe(false)

    const chips = screen.getByRole('group', { name: 'Tipo de vocabulario' })
    const corp = within(chips).getByRole('button', { name: 'SKOS corporativos' })
    await user.click(corp)
    expect(corp).toHaveAttribute('aria-pressed', 'true')
    expect(within(chips).getByRole('button', { name: 'Todos' })).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(vocabCalls(fetchMock).at(-1)!.searchParams.get('kind')).toBe('skos_corp'))
    expect(await screen.findByRole('link', { name: 'Esquema corporativo de prueba' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'SKOS corporativos' })).toBeInTheDocument()
    expect(screen.getByText('1 vocabulario')).toBeInTheDocument()

    // La estadística activa vuelve a «Todos» al pulsarla otra vez.
    const stats = screen.getByRole('group', { name: 'Recuento por tipo' })
    const own = within(stats).getByRole('button', { name: /Ontologías propias/ })
    await user.click(own)
    expect(own).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(vocabCalls(fetchMock).at(-1)!.searchParams.get('kind')).toBe('own'))
    await user.click(own)
    expect(own).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(vocabCalls(fetchMock).at(-1)!.searchParams.has('kind')).toBe(false))
  })

  it('lanza q con debounce al escribir', async () => {
    const fetchMock = mockVocab()
    const { user } = renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    await user.type(screen.getByLabelText('Buscar vocabulario'), 'pru')
    await waitFor(() => expect(vocabCalls(fetchMock).at(-1)!.searchParams.get('q')).toBe('pru'))
    expect(vocabCalls(fetchMock).length).toBeLessThan(4)
  })

  it('pinta cada tipo de tarjeta con rdfType, tipo, estado, prefijo, espacio de nombres, métricas y versión', async () => {
    mockVocab()
    renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })

    const own = cardOf('Ontología de prueba')
    expect(within(own).getByText('owl:Ontology')).toBeInTheDocument()
    expect(within(own).getByText('Ontología propia')).toBeInTheDocument()
    expect(within(own).getByText('Publicada')).toBeInTheDocument()
    expect(within(own).getByText('pru:')).toBeInTheDocument()
    expect(within(own).getByText(/onto\/onto-prueba#/)).toBeInTheDocument()
    expect(within(own).getByText('13 clases · 7 propiedades')).toBeInTheDocument()
    expect(within(own).getByText('v1.2.0')).toBeInTheDocument()
    expect(within(own).queryByText('Sintético')).not.toBeInTheDocument()

    const corp = cardOf('Esquema corporativo de prueba')
    expect(within(corp).getByText('skos:ConceptScheme')).toBeInTheDocument()
    expect(within(corp).getByText('SKOS corporativo')).toBeInTheDocument()
    expect(within(corp).getByText('Borrador')).toBeInTheDocument()
    expect(within(corp).getByText('[N] conceptos')).toBeInTheDocument()
    expect(within(corp).getByText('Sintético')).toBeInTheDocument()
    expect(within(corp).queryByText('Dataset sintético')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Esquema corporativo de prueba' })).toHaveAttribute(
      'href',
      '/vocabularios/corp/corp-prueba',
    )

    const domain = cardOf('Esquema de dominio de prueba')
    expect(within(domain).getByText('SKOS de dominio')).toBeInTheDocument()
    expect(within(domain).getByText('6 conceptos')).toBeInTheDocument()
    expect(within(domain).getByText('v1.0')).toBeInTheDocument()
  })

  it('enlaza las ontologías externas a su IRI oficial y muestra [VERSIÓN] sin versión', async () => {
    mockVocab()
    renderApp('/vocabularios')
    const link = await screen.findByRole('link', { name: /Ontología externa de prueba/ })
    expect(link).toHaveAttribute('href', 'https://externa.test/onto/')
    expect(link).toHaveAccessibleName('Ontología externa de prueba (IRI oficial, sitio externo)')
    const card = link.closest('article')!
    expect(within(card).getByText('Referenciada')).toBeInTheDocument()
    expect(within(card).getByText('Externa · referencia')).toBeInTheDocument()
    expect(within(card).getByText('[VERSIÓN]')).toBeInTheDocument()
  })

  it.each([
    ['javascript:', 'javascript:alert(1)'],
    ['con placeholder', 'https://externa.test/[VERSIÓN]/onto'],
  ])('no enlaza una ontología externa con IRI %s: muestra el texto', async (_case, uri) => {
    const external = vocabCardsFixture()[1]
    mockVocab(() => vocabPageFixture([{ ...external, uri, namespace: null }]))
    renderApp('/vocabularios')
    const title = await screen.findByText('Ontología externa de prueba')
    expect(title.closest('a')).toBeNull()
    expect(screen.queryByRole('link', { name: /Ontología externa de prueba/ })).not.toBeInTheDocument()
    const card = title.closest('article')!
    expect(within(card).queryAllByRole('link')).toHaveLength(0)
    expect(document.querySelector(`a[href="${uri}"]`)).toBeNull()
  })

  it('decisión 51: una externa con slug enlaza a su ficha y muestra sus métricas', async () => {
    const external = vocabCardsFixture()[1]
    mockVocab(() => vocabPageFixture([{ ...external, slug: 'ext', version: '2.0', metrics: { classes: 5, properties: 3 } }]))
    renderApp('/vocabularios')
    const link = await screen.findByRole('link', { name: 'Ontología externa de prueba' })
    expect(link).toHaveAttribute('href', '/ontologias/externas/ext')
    const card = link.closest('article')!
    expect(within(card).getByText('5 clases · 3 propiedades')).toBeInTheDocument()
    expect(within(card).getByText('v2.0')).toBeInTheDocument()
  })

  it('muestra «Métricas sin calcular» si una ontología propia no tiene métricas', async () => {
    mockVocab(() => vocabPageFixture([{ ...vocabCardsFixture()[0], metrics: null }]))
    renderApp('/vocabularios')
    await screen.findByRole('link', { name: 'Ontología de prueba' })
    expect(screen.getByText('Métricas sin calcular')).toBeInTheDocument()
  })

  it('muestra los estados de carga, vacío y error con reintento', async () => {
    let fail = true
    mockVocab(() => (fail ? jsonResponse({ detail: 'Service Unavailable' }, 503) : vocabPageFixture([])))
    const { user } = renderApp('/vocabularios')
    expect(screen.getByRole('status')).toHaveTextContent('Cargando vocabularios…')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se han podido cargar los vocabularios.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('Ningún vocabulario coincide con los filtros.')).toBeInTheDocument()
    expect(screen.getByText('0 vocabularios')).toBeInTheDocument()
  })
})
