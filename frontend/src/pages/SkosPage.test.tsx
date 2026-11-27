import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ConceptDetail, SchemeDetail } from '../api'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'
import { conceptFixture, corpSchemeFixture, schemeFixture, vocabPageFixture } from '../test/vocabFixtures'

const SCHEME_PATH = '/schemes/esq-prueba'

interface MockOptions {
  scheme?: () => SchemeDetail | Response
  concept?: (slug: string) => ConceptDetail | Response
}

function conceptFor(slug: string): ConceptDetail {
  const label = slug.replace('concepto-', 'Concepto ').replace('grupo-', 'Grupo ').toUpperCase()
  return conceptFixture({ slug, uri: `http://uri.test/itot/vocab/esq-prueba/${slug}`, pref_label: label })
}

function mockSkos({ scheme = () => schemeFixture(), concept = conceptFor }: MockOptions = {}) {
  return mockFetch({
    '/vocabularies': () => jsonResponse(vocabPageFixture()),
    [SCHEME_PATH]: () => {
      const result = scheme()
      return result instanceof Response ? result : jsonResponse(result)
    },
    '/schemes/corp/corp-prueba': () => jsonResponse(corpSchemeFixture()),
    ...Object.fromEntries(
      ['grupo-a', 'concepto-a1', 'concepto-a2', 'concepto-a2x', 'grupo-b', 'concepto-b1', 'no-existe'].map((slug) => [
        `${SCHEME_PATH}/concepts/${slug}`,
        () => {
          if (slug === 'no-existe') return jsonResponse({ detail: 'Not Found' }, 404)
          const result = concept(slug)
          return result instanceof Response ? result : jsonResponse(result)
        },
      ]),
    ),
  })
}

async function renderSkos(route = '/vocabularios/esq-prueba') {
  const result = renderApp(route)
  await screen.findByRole('heading', { level: 1, name: 'Esquema de dominio de prueba' })
  return result
}

function tree() {
  return screen.getByRole('tree', { name: 'Conceptos de Esquema de dominio de prueba' })
}

function item(name: string) {
  return within(tree()).getByRole('treeitem', { name })
}

function conceptCalls(fetchMock: ReturnType<typeof mockFetch>): string[] {
  return fetchMock.mock.calls
    .map(([u]) => new URL(String(u)).pathname)
    .filter((p) => p.includes('/concepts/'))
}

describe('Navegador SKOS', () => {
  it('muestra migas, etiquetas, título, prefijo y espacio de nombres del esquema', async () => {
    mockSkos()
    await renderSkos()
    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('href', '/vocabularios')
    expect(within(crumbs).getByText('SKOS de dominio')).toBeInTheDocument()
    expect(within(crumbs).getByText('esq-prueba')).toHaveAttribute('aria-current', 'page')

    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('skos:ConceptScheme')).toBeInTheDocument()
    expect(within(header).getByText('SKOS de dominio')).toBeInTheDocument()
    expect(within(header).getByText('OT / ICS')).toBeInTheDocument()
    expect(within(header).getByText('v1.0')).toBeInTheDocument()
    expect(within(header).getByText('esq:')).toBeInTheDocument()
    expect(within(header).queryByText('Sintético')).not.toBeInTheDocument()
    expect(within(header).queryByText(/Responsable/)).not.toBeInTheDocument()
  })

  it('ofrece «Exportar Turtle» desde /schemes/…/rdf y oculta «Nuevo concepto»', async () => {
    mockSkos()
    await renderSkos()
    expect(screen.getByRole('link', { name: 'Exportar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/schemes/esq-prueba/rdf?format=turtle&download=1',
    )
    expect(screen.queryByRole('button', { name: 'Nuevo concepto' })).not.toBeInTheDocument()
  })

  it('lista los esquemas de dominio y corporativos y marca el actual', async () => {
    mockSkos()
    await renderSkos()
    const schemes = screen.getByRole('navigation', { name: 'Esquemas' })
    await within(schemes).findByRole('heading', { name: 'De dominio' })
    expect(within(schemes).getByRole('heading', { name: 'Corporativos' })).toBeInTheDocument()
    const current = within(schemes).getByRole('link', { name: 'Esquema de dominio de prueba' })
    expect(current).toHaveAttribute('href', '/vocabularios/esq-prueba')
    expect(current).toHaveAttribute('aria-current', 'page')
    const corp = within(schemes).getByRole('link', { name: 'Esquema corporativo de prueba' })
    expect(corp).toHaveAttribute('href', '/vocabularios/corp/corp-prueba')
    expect(corp).not.toHaveAttribute('aria-current')
    // Color del dominio si el esquema lo tiene; si no, el del tipo.
    expect(current.querySelector('.sidebar__swatch')?.getAttribute('style')).toContain('var(--domain-ot)')
    expect(corp.querySelector('.sidebar__swatch')?.getAttribute('style')).toContain('var(--kind-corp)')
    // Las ontologías no son esquemas.
    expect(within(schemes).queryByRole('link', { name: /Ontología/ })).not.toBeInTheDocument()
  })

  it('pinta el árbol con el patrón tree: niveles, aria-expanded y aria-selected', async () => {
    mockSkos()
    await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')

    const grupoA = item('Grupo A')
    expect(grupoA).toHaveAttribute('aria-level', '1')
    expect(grupoA).toHaveAttribute('aria-expanded', 'true')
    expect(item('Concepto A1')).toHaveAttribute('aria-level', '2')
    expect(item('Concepto A1')).toHaveAttribute('aria-selected', 'true')
    expect(item('Concepto A1')).toHaveAttribute('tabindex', '0')
    expect(item('Concepto A1')).not.toHaveAttribute('aria-expanded')
    expect(item('Concepto Á2')).toHaveAttribute('aria-expanded', 'false')
    expect(item('Concepto Á2')).toHaveAttribute('aria-selected', 'false')
    expect(item('Concepto Á2')).toHaveAttribute('tabindex', '-1')
    expect(within(tree()).queryByRole('treeitem', { name: 'Concepto A2X' })).not.toBeInTheDocument()
    expect(screen.getByText('6 conceptos')).toBeInTheDocument()
  })

  it('se navega con el teclado: flechas, Inicio, Fin, expandir, contraer e Intro para seleccionar', async () => {
    const fetchMock = mockSkos()
    const { user } = await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')
    await screen.findByRole('heading', { level: 2, name: 'CONCEPTO A1' })

    await user.click(item('Concepto A1'))
    await user.keyboard('{ArrowDown}')
    expect(item('Concepto Á2')).toHaveFocus()

    // Derecha abre la rama; otra vez baja al primer hijo; izquierda vuelve al padre.
    await user.keyboard('{ArrowRight}')
    expect(item('Concepto Á2')).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{ArrowRight}')
    expect(item('Concepto A2X')).toHaveFocus()
    expect(item('Concepto A2X')).toHaveAttribute('aria-level', '3')
    await user.keyboard('{ArrowLeft}')
    expect(item('Concepto Á2')).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(item('Concepto Á2')).toHaveAttribute('aria-expanded', 'false')

    await user.keyboard('{End}')
    expect(item('Concepto B1')).toHaveFocus()
    await user.keyboard('{Home}')
    expect(item('Grupo A')).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(item('Grupo A')).toHaveFocus()

    // Intro selecciona: cambia ?concepto= y carga el detalle.
    await user.keyboard('{End}{Enter}')
    expect(await screen.findByRole('heading', { level: 2, name: 'CONCEPTO B1' })).toBeInTheDocument()
    expect(item('Concepto B1')).toHaveAttribute('aria-selected', 'true')
    expect(item('Concepto A1')).toHaveAttribute('aria-selected', 'false')
    expect(conceptCalls(fetchMock).at(-1)).toBe(`${SCHEME_PATH}/concepts/concepto-b1`)

    // Espacio también selecciona.
    await user.keyboard('{ArrowUp} ')
    expect(await screen.findByRole('heading', { level: 2, name: 'GRUPO B' })).toBeInTheDocument()
  })

  it('filtra el árbol sin distinguir acentos, abre las ramas y conserva los antepasados', async () => {
    mockSkos()
    const { user } = await renderSkos()
    const input = screen.getByLabelText('Filtrar conceptos')
    expect(input).toHaveAttribute('placeholder', 'prefLabel o altLabel')

    await user.type(input, 'a2x')
    expect(item('Grupo A')).toBeInTheDocument()
    expect(item('Concepto Á2')).toHaveAttribute('aria-expanded', 'true')
    expect(item('Concepto A2X')).toBeInTheDocument()
    expect(within(tree()).queryByRole('treeitem', { name: 'Concepto A1' })).not.toBeInTheDocument()
    expect(within(tree()).queryByRole('treeitem', { name: 'Grupo B' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, 'concepto a2')
    expect(item('Concepto Á2')).toBeInTheDocument()

    // También busca por altLabel.
    await user.clear(input)
    await user.type(input, 'sinonimo beta')
    expect(item('Grupo B')).toBeInTheDocument()
    expect(item('Concepto B1')).toBeInTheDocument()
    expect(within(tree()).queryByRole('treeitem', { name: 'Grupo A' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, 'zzz')
    expect(screen.queryByRole('tree')).not.toBeInTheDocument()
    expect(screen.getByText('Ningún concepto coincide con el filtro.')).toBeInTheDocument()
  })

  it('selecciona con el ratón y sin ?concepto= muestra el primer concepto', async () => {
    const fetchMock = mockSkos()
    const { user } = await renderSkos()
    expect(await screen.findByRole('heading', { level: 2, name: 'GRUPO A' })).toBeInTheDocument()
    expect(item('Grupo A')).toHaveAttribute('aria-selected', 'true')
    await user.click(within(item('Concepto B1')).getByText('Concepto B1'))
    expect(await screen.findByRole('heading', { level: 2, name: 'CONCEPTO B1' })).toBeInTheDocument()
    expect(conceptCalls(fetchMock)).toEqual([`${SCHEME_PATH}/concepts/grupo-a`, `${SCHEME_PATH}/concepts/concepto-b1`])
  })

  it('muestra el detalle del concepto: prefLabel por idioma, altLabel, broader, related y usos', async () => {
    mockSkos({ concept: () => conceptFixture() })
    await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')
    const article = (await screen.findByRole('heading', { level: 2, name: 'Concepto A1' })).closest('article') as HTMLElement

    expect(within(article).getByText('skos:Concept · esq:concepto-a1')).toBeInTheDocument()
    expect(within(article).getByText('Definición de prueba del concepto A1.')).toBeInTheDocument()
    const terms = within(article)
      .getAllByText(/^skos:prefLabel/, { selector: 'dt' })
      .map((dt) => dt.textContent)
    expect(terms).toEqual(['skos:prefLabel @es', 'skos:prefLabel @ca', 'skos:prefLabel @en'])
    const en = within(article).getByText('skos:prefLabel @en', { selector: 'dt' }).nextElementSibling!
    expect(en).toHaveTextContent('Concept A1 (en)')
    expect(en).toHaveAttribute('lang', 'en')
    expect(within(article).getByText('skos:altLabel', { selector: 'dt' }).nextElementSibling).toHaveTextContent(
      'Alternativa A1 @es',
    )
    const broader = within(article).getByText('skos:broader', { selector: 'dt' }).nextElementSibling as HTMLElement
    expect(within(broader).getByRole('link', { name: 'Grupo A' })).toHaveAttribute(
      'href',
      '/vocabularios/esq-prueba?concepto=grupo-a',
    )
    const related = within(article).getByText('skos:related', { selector: 'dt' }).nextElementSibling as HTMLElement
    expect(within(related).getByRole('link', { name: 'Concepto B1' })).toHaveAttribute(
      'href',
      '/vocabularios/esq-prueba?concepto=concepto-b1',
    )
    expect(within(article).getByText('Sin mapeos externos todavía')).toBeInTheDocument()

    expect(within(article).getByRole('heading', { level: 3, name: 'Recursos que usan este concepto' })).toBeInTheDocument()
    const dataset = within(article).getByRole('link', { name: /Dataset de prueba/ })
    expect(dataset).toHaveAttribute('href', '/datasets/dataset-prueba')
    expect(dataset).toHaveTextContent('dcat:theme')
    const onto = within(article).getByRole('link', { name: /Ontología de prueba/ })
    expect(onto).toHaveAttribute('href', '/ontologias/onto-prueba')
    expect(onto).toHaveTextContent('owl:Ontology · dct:subject')
  })

  it('muestra los mapeos externos y no enlaza los placeholders', async () => {
    mockSkos({
      concept: () =>
        conceptFixture({
          exact_match: ['https://externo.test/termino'],
          close_match: ['https://www.wikidata.test/wiki/[QID]'],
        }),
    })
    await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')
    const article = (await screen.findByRole('heading', { level: 2, name: 'Concepto A1' })).closest('article') as HTMLElement
    const maps = within(article).getByText('Mapeos externos', { selector: 'dt' }).nextElementSibling as HTMLElement
    expect(within(maps).getByText('skos:exactMatch')).toBeInTheDocument()
    expect(within(maps).getByRole('link', { name: 'https://externo.test/termino' })).toHaveAttribute(
      'href',
      'https://externo.test/termino',
    )
    expect(within(maps).getByText('skos:closeMatch')).toBeInTheDocument()
    expect(within(maps).getByText('https://www.wikidata.test/wiki/[QID]')).toBeInTheDocument()
    expect(within(maps).queryByRole('link', { name: /\[QID\]/ })).not.toBeInTheDocument()
  })

  it('indica cuando ningún recurso usa el concepto y sin broader ni related', async () => {
    mockSkos({
      concept: () =>
        conceptFixture({ broader: [], related: [], alt_labels: [], used_by: { datasets: [], ontologies: [] } }),
    })
    await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')
    const article = (await screen.findByRole('heading', { level: 2, name: 'Concepto A1' })).closest('article') as HTMLElement
    expect(within(article).getByText('Ningún recurso del catálogo lo referencia todavía.')).toBeInTheDocument()
    expect(within(article).queryByRole('link')).not.toBeInTheDocument()
    expect(within(article).getByText('skos:broader', { selector: 'dt' }).nextElementSibling).toHaveTextContent('—')
    expect(within(article).getByText('skos:altLabel', { selector: 'dt' }).nextElementSibling).toHaveTextContent('—')
  })

  it('abre la rama del concepto seleccionado al seguir un enlace related', async () => {
    mockSkos({
      concept: (slug) =>
        slug === 'concepto-a1'
          ? conceptFixture({
              related: [{ uri: 'http://uri.test/itot/vocab/esq-prueba/concepto-a2x', label: 'Concepto A2X', scheme: null }],
            })
          : conceptFor(slug),
    })
    const { user } = await renderSkos('/vocabularios/esq-prueba?concepto=concepto-a1')
    const article = (await screen.findByRole('heading', { level: 2, name: 'Concepto A1' })).closest('article') as HTMLElement
    expect(within(tree()).queryByRole('treeitem', { name: 'Concepto A2X' })).not.toBeInTheDocument()
    await user.click(within(article).getByRole('link', { name: 'Concepto A2X' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'CONCEPTO A2X' })).toBeInTheDocument()
    expect(item('Concepto A2X')).toHaveAttribute('aria-selected', 'true')
    expect(item('Concepto Á2')).toHaveAttribute('aria-expanded', 'true')
  })

  it('muestra «Concepto no encontrado» si ?concepto= no existe', async () => {
    mockSkos()
    await renderSkos('/vocabularios/esq-prueba?concepto=no-existe')
    expect(await screen.findByRole('heading', { level: 2, name: 'Concepto no encontrado' })).toBeInTheDocument()
  })

  it('usa la ruta corporativa: /schemes/corp/, Responsable, [N], [VERSIÓN], Sintético y árbol vacío', async () => {
    const fetchMock = mockFetch({
      '/vocabularies': () => jsonResponse(vocabPageFixture()),
      '/schemes/corp/corp-prueba': () => jsonResponse(corpSchemeFixture({ synthetic: true })),
    })
    renderApp('/vocabularios/corp/corp-prueba')
    await screen.findByRole('heading', { level: 1, name: 'Esquema corporativo de prueba' })
    expect(fetchMock.mock.calls.map(([u]) => new URL(String(u)).pathname)).toContain('/schemes/corp/corp-prueba')

    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByText('SKOS corporativos')).toBeInTheDocument()
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('SKOS corporativo')).toBeInTheDocument()
    expect(within(header).getByText('Borrador')).toBeInTheDocument()
    expect(within(header).getByText('[VERSIÓN]')).toBeInTheDocument()
    expect(within(header).getByText('Sintético')).toBeInTheDocument()
    expect(within(header).getByText('Responsable: [RESPONSABLE]')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Exportar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/schemes/corp/corp-prueba/rdf?format=turtle&download=1',
    )
    expect(screen.getByText('[N] conceptos')).toBeInTheDocument()
    expect(screen.getByText('Este esquema no tiene conceptos cargados todavía.')).toBeInTheDocument()
    expect(screen.getByText('Este esquema no tiene conceptos que mostrar.')).toBeInTheDocument()

    const schemes = screen.getByRole('navigation', { name: 'Esquemas' })
    expect(await within(schemes).findByRole('link', { name: 'Esquema corporativo de prueba' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('muestra los esquemas auxiliares (kind auxiliary) con una etiqueta neutra', async () => {
    const uri = 'http://uri.test/itot/vocab/dominio'
    mockFetch({
      '/vocabularies': () => jsonResponse(vocabPageFixture()),
      '/schemes/dominio': () =>
        jsonResponse(
          schemeFixture({
            slug: 'dominio',
            kind: 'auxiliary',
            uri,
            title: 'Esquema auxiliar de prueba',
            prefix: null,
            namespace: null,
            domain: null,
            concept_count: 1,
            tree: [{ uri: `${uri}/ot`, slug: 'ot', label: 'Dominio OT de prueba', top_concept: true, alt_labels: [], children: [] }],
          }),
        ),
      '/schemes/dominio/concepts/ot': () =>
        jsonResponse(
          conceptFixture({
            uri: `${uri}/ot`,
            slug: 'ot',
            pref_label: 'Dominio OT de prueba',
            broader: [],
            related: [],
            used_by: { datasets: [], ontologies: [] },
          }),
        ),
    })
    renderApp('/vocabularios/dominio?concepto=ot')
    await screen.findByRole('heading', { level: 1, name: 'Esquema auxiliar de prueba' })
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('Esquema auxiliar')).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByText('Esquemas auxiliares')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2, name: 'Dominio OT de prueba' })).toBeInTheDocument()
    expect(
      within(screen.getByRole('tree', { name: 'Conceptos de Esquema auxiliar de prueba' })).getByRole('treeitem', {
        name: 'Dominio OT de prueba',
      }),
    ).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('muestra «Esquema no encontrado» si la API responde 404', async () => {
    mockFetch({ '/vocabularies': () => jsonResponse(vocabPageFixture()) })
    renderApp('/vocabularios/no-existe')
    expect(await screen.findByRole('heading', { level: 1, name: 'Esquema no encontrado' })).toBeInTheDocument()
  })

  it('muestra un error accesible si falla el esquema y permite reintentar', async () => {
    let fail = true
    mockSkos({ scheme: () => (fail ? jsonResponse({ detail: 'Service Unavailable' }, 503) : schemeFixture()) })
    const { user } = renderApp('/vocabularios/esq-prueba')
    expect(screen.getByRole('status')).toHaveTextContent('Cargando esquema…')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se ha podido cargar el esquema.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Esquema de dominio de prueba'))
  })

  it('marca Vocabularios en la navegación y muestra «Tipos de vocabulario»', async () => {
    mockSkos()
    await renderSkos()
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('aria-current', 'true')
    expect(within(nav).getByRole('heading', { name: 'Tipos de vocabulario' })).toBeInTheDocument()
  })

  it('QA-51-02: el nombre de cada treeitem es el texto visible de su fila, sin aria-label ni los hijos', async () => {
    mockSkos()
    await renderSkos()
    const items = within(tree()).getAllByRole('treeitem')
    expect(items.length).toBeGreaterThan(1)
    for (const node of items) {
      expect(node).not.toHaveAttribute('aria-label')
      expect(node).not.toHaveAttribute('aria-labelledby')
      expect(node).toHaveAccessibleName(node.textContent!.trim())
    }
    // El grupo de hijos ya no está dentro del treeitem: el nombre del padre no los incluye.
    expect(item('Grupo B')).toHaveAccessibleName('Grupo B')
    expect(within(item('Grupo B')).queryByText('Concepto B1')).not.toBeInTheDocument()
  })
})
