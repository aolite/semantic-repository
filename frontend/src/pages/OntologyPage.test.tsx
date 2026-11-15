import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { OntologyDetail } from '../api'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'
import { ontologyFixture } from '../test/vocabFixtures'

const PATH = '/ontologies/onto-prueba'

function mockOntology(detail: (url: URL) => OntologyDetail | Response = () => ontologyFixture()) {
  return mockFetch({
    [PATH]: (url) => {
      const result = detail(new URL(url))
      return result instanceof Response ? result : jsonResponse(result)
    },
  })
}

async function renderOntology(route = '/ontologias/onto-prueba') {
  const result = renderApp(route)
  await screen.findByRole('heading', { level: 1, name: 'Ontología de prueba' })
  return result
}

function section(name: string) {
  return screen.getByRole('heading', { level: 2, name }).closest('section, aside') as HTMLElement
}

function field(container: HTMLElement, term: string | RegExp) {
  return within(container).getByText(term, { selector: 'dt' }).nextElementSibling as HTMLElement
}

describe('Ficha de ontología', () => {
  it('muestra migas, etiquetas, título, prefijo y URI', async () => {
    mockOntology()
    await renderOntology()

    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('href', '/vocabularios')
    expect(within(crumbs).getByText('Ontologías propias')).toBeInTheDocument()
    expect(within(crumbs).getByText('onto-prueba')).toHaveAttribute('aria-current', 'page')

    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('owl:Ontology')).toBeInTheDocument()
    expect(within(header).getByText('Ontología propia')).toBeInTheDocument()
    expect(within(header).getByText('Publicada')).toBeInTheDocument()
    expect(within(header).getByText('v1.2.0 · actual')).toBeInTheDocument()
    expect(within(header).getByText('pru:')).toBeInTheDocument()
    expect(within(header).getByText('http://uri.test/itot/onto/onto-prueba')).toBeInTheDocument()
    expect(within(header).queryByText('Sintético')).not.toBeInTheDocument()
  })

  it('marca la ontología en la navegación como parte de Vocabularios', async () => {
    mockOntology()
    await renderOntology()
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('aria-current', 'true')
    expect(within(nav).getByRole('heading', { name: 'Tipos de vocabulario' })).toBeInTheDocument()
  })

  it('marca las ontologías sintéticas con «Sintético»', async () => {
    mockOntology(() => ontologyFixture({ synthetic: true }))
    await renderOntology()
    expect(screen.getByText('Sintético')).toBeInTheDocument()
    expect(screen.queryByText('Dataset sintético')).not.toBeInTheDocument()
  })

  it('descarga Turtle y las serializaciones desde /ontologies/{slug}/rdf', async () => {
    mockOntology()
    await renderOntology()
    expect(screen.getByRole('link', { name: 'Descargar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/onto-prueba/rdf?format=turtle&download=1',
    )
    const meta = section('Metadatos')
    const formats = field(meta, 'Serializaciones')
    expect(within(formats).getByRole('link', { name: 'Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/onto-prueba/rdf?format=turtle&download=1',
    )
    expect(within(formats).getByRole('link', { name: 'RDF/XML' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/onto-prueba/rdf?format=rdfxml&download=1',
    )
    expect(within(formats).getByRole('link', { name: 'JSON-LD' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/onto-prueba/rdf?format=jsonld&download=1',
    )
  })

  it('oculta los botones sin función todavía', async () => {
    mockOntology()
    await renderOntology()
    expect(screen.queryByRole('button', { name: 'Documentación' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Documentación' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copiar URI' })).toBeInTheDocument()
  })

  it('muestra las métricas reales del fichero, el perfil, la consistencia y la cobertura', async () => {
    mockOntology()
    await renderOntology()
    const metrics = section('Métricas')
    expect(within(metrics).getByText('calculadas en backend · v1.2.0')).toBeInTheDocument()
    const tiles = within(metrics).getByRole('list', { name: 'Métricas OWL' })
    const values = within(tiles)
      .getAllByRole('listitem')
      .map((li) => li.textContent)
    expect(values).toEqual([
      '13Clases',
      '5Propiedades de objeto',
      '2Propiedades de datos',
      '4Individuos',
      '40Axiomas lógicos',
      '2Imports',
    ])
    expect(field(metrics, 'Perfil OWL')).toHaveTextContent('OWL 2 DL')
    expect(field(metrics, 'Perfil OWL')).toHaveTextContent('Compatible con OWL 2 RL (aproximado)')
    // La expresividad DL llega null: «Sin calcular».
    expect(field(metrics, 'Expresividad DL')).toHaveTextContent('Sin calcular')
    // El razonador es el que devuelve la API, no el del prototipo.
    const consistency = field(metrics, 'Consistencia (Razonador de prueba)')
    expect(consistency).toHaveTextContent('Consistente · 0 clases insatisfacibles')
    expect(consistency).toHaveTextContent('Razonado sin las ontologías importadas')
    expect(within(metrics).queryByText(/HermiT/)).not.toBeInTheDocument()
    expect(field(metrics, 'Cobertura de documentación')).toHaveTextContent(
      'rdfs:comment en 95 % de clases y propiedades',
    )
  })

  it('muestra el motivo cuando consistent es null', async () => {
    const base = ontologyFixture()
    mockOntology(() =>
      ontologyFixture({
        consistency: {
          ...base.consistency!,
          consistent: null,
          unsatisfiable_classes: null,
          detail: 'Motivo de prueba',
        },
      }),
    )
    await renderOntology()
    expect(field(section('Métricas'), /^Consistencia/)).toHaveTextContent('No se ha podido comprobar: Motivo de prueba')
  })

  it('muestra la inconsistencia y las clases insatisfacibles', async () => {
    const base = ontologyFixture()
    mockOntology(() =>
      ontologyFixture({
        consistency: {
          ...base.consistency!,
          consistent: false,
          unsatisfiable_classes: 1,
          unsatisfiable: ['http://uri.test/itot/onto/onto-prueba#Rota'],
          detail: 'Detalle de prueba',
        },
      }),
    )
    await renderOntology()
    const value = field(section('Métricas'), /^Consistencia/)
    expect(value).toHaveTextContent('Inconsistente · Detalle de prueba')
    expect(within(value).getByRole('list', { name: 'Clases insatisfacibles' })).toHaveTextContent('#Rota')
  })

  it('indica que las métricas no se han calculado si llegan null', async () => {
    mockOntology(() => ontologyFixture({ metrics: null, profile: null, consistency: null, documentation: null }))
    await renderOntology()
    const metrics = section('Métricas')
    expect(within(metrics).getByText('Las métricas de esta versión no se han calculado todavía.')).toBeInTheDocument()
    expect(within(metrics).queryByRole('list', { name: 'Métricas OWL' })).not.toBeInTheDocument()
    expect(field(metrics, 'Perfil OWL')).toHaveTextContent('Sin calcular')
    expect(field(metrics, 'Consistencia')).toHaveTextContent('Sin calcular')
    expect(field(metrics, 'Cobertura de documentación')).toHaveTextContent('Sin calcular')
  })

  it('lista imports y alineamientos con relación abreviada y [VERSIÓN] sin versión', async () => {
    mockOntology()
    await renderOntology()
    const table = within(section('Imports y alineamientos')).getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByRole('link', { name: 'Importada de prueba' })).toHaveAttribute(
      'href',
      'https://importada.test/onto/',
    )
    expect(rows[0]).toHaveTextContent('owl:imports')
    expect(rows[0]).toHaveTextContent('3.0')
    expect(rows[1]).toHaveTextContent('Alineada de prueba')
    expect(rows[1]).toHaveTextContent('rdfs:subClassOf')
    expect(rows[1]).toHaveTextContent('2 axiomas')
    expect(rows[1]).toHaveTextContent('[VERSIÓN]')
    expect(within(rows[1]).getByText('Ver correspondencias')).toBeInTheDocument()
  })

  it('muestra el versionado con versionIRI, priorVersion, compatibilidad e historial', async () => {
    mockOntology()
    await renderOntology()
    const versioning = section('Versionado')
    expect(field(versioning, 'owl:versionIRI')).toHaveTextContent('http://uri.test/itot/onto/onto-prueba/1.2.0')
    expect(within(field(versioning, 'owl:priorVersion')).getByRole('link', { name: 'onto-prueba/1.1.0' })).toHaveAttribute(
      'href',
      '/ontologias/onto-prueba?version=1.1.0',
    )
    expect(field(versioning, 'Compatibilidad')).toHaveTextContent('owl:backwardCompatibleWith 1.1.0')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.2.0' })).toHaveAttribute('href', '/ontologias/onto-prueba')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.2.0' })).toHaveAttribute('aria-current', 'page')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.0.0' })).toHaveAttribute(
      'href',
      '/ontologias/onto-prueba?version=1.0.0',
    )
    expect(within(versioning).getAllByText('[FECHA]')).toHaveLength(3)
  })

  it('muestra una versión antigua con ?version=: pide la versión, URI de la versión y descargas con version', async () => {
    const fixture = ontologyFixture()
    const old = ontologyFixture({
      versioning: {
        ...fixture.versioning,
        version: '1.0.0',
        version_iri: 'http://uri.test/itot/onto/onto-prueba/1.0.0',
        prior_version: null,
        backward_compatible_with: [],
      },
    })
    const fetchMock = mockOntology((url) => (url.searchParams.get('version') === '1.0.0' ? old : fixture))
    await renderOntology('/ontologias/onto-prueba?version=1.0.0')

    expect(String(fetchMock.mock.calls[0][0])).toBe(`http://api.test${PATH}?version=1.0.0`)
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('v1.0.0')).toBeInTheDocument()
    expect(screen.queryByText(/· actual/)).not.toBeInTheDocument()
    expect(within(header).getByText('http://uri.test/itot/onto/onto-prueba/1.0.0')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Descargar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/onto-prueba/rdf?format=turtle&version=1.0.0&download=1',
    )
    const versioning = section('Versionado')
    expect(field(versioning, 'owl:priorVersion')).toHaveTextContent('Ninguna')
    expect(field(versioning, 'Compatibilidad')).toHaveTextContent('Sin declarar')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.0.0' })).toHaveAttribute('aria-current', 'page')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.2.0' })).not.toHaveAttribute('aria-current')
  })

  it('enlaza los datasets que la usan y deja [PROYECTO]', async () => {
    mockOntology()
    await renderOntology()
    const usage = section('Uso en el catálogo')
    const link = within(usage).getByRole('link', { name: /Dataset de prueba/ })
    expect(link).toHaveAttribute('href', '/datasets/dataset-prueba')
    expect(link).toHaveTextContent('dcat:Dataset · v2.1.0')
    expect(within(usage).getByText('Proyectos que la aplican: [PROYECTO]')).toBeInTheDocument()
  })

  it('indica cuando ningún dataset la usa', async () => {
    mockOntology(() => ontologyFixture({ used_by_datasets: [] }))
    await renderOntology()
    expect(within(section('Uso en el catálogo')).getByText('Ningún dataset del catálogo la usa todavía.')).toBeInTheDocument()
  })

  it('muestra los metadatos VANN y DCT con los placeholders del prototipo', async () => {
    mockOntology()
    await renderOntology()
    const meta = section('Metadatos')
    expect(field(meta, 'vann:preferredNamespacePrefix')).toHaveTextContent('pru')
    expect(field(meta, 'vann:preferredNamespaceUri')).toHaveTextContent('http://uri.test/itot/onto/onto-prueba#')
    expect(field(meta, 'dct:creator')).toHaveTextContent('[AUTORES]')
    expect(field(meta, 'dct:publisher')).toHaveTextContent('Publicador de prueba')
    expect(field(meta, 'dct:license')).toHaveTextContent('[LICENCIA]')
    expect(field(meta, 'dct:issued · dct:modified')).toHaveTextContent('[FECHA] · [FECHA]')
    expect(field(meta, 'Repositorio')).toHaveTextContent('[REPOSITORIO GIT]')
  })

  it('enlaza los vocabularios SKOS usados al navegador, incluida la ruta corporativa', async () => {
    mockOntology()
    await renderOntology()
    const used = field(section('Metadatos'), 'Vocabularios SKOS usados')
    expect(within(used).getByRole('link', { name: 'Esquema de dominio de prueba' })).toHaveAttribute(
      'href',
      '/vocabularios/esq-prueba',
    )
    expect(within(used).getByRole('link', { name: 'Esquema corporativo de prueba' })).toHaveAttribute(
      'href',
      '/vocabularios/corp/corp-prueba',
    )
  })

  it('muestra «Ontología no encontrada» si la API responde 404', async () => {
    mockFetch({})
    renderApp('/ontologias/no-existe')
    expect(await screen.findByRole('heading', { level: 1, name: 'Ontología no encontrada' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a Vocabularios' })).toHaveAttribute('href', '/vocabularios')
  })

  it('muestra un error accesible si la API falla y permite reintentar', async () => {
    let fail = true
    mockOntology(() => (fail ? jsonResponse({ detail: 'Service Unavailable' }, 503) : ontologyFixture()))
    const { user } = renderApp('/ontologias/onto-prueba')
    expect(screen.getByRole('status')).toHaveTextContent('Cargando ontología…')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se ha podido cargar la ontología.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Ontología de prueba' })).toBeInTheDocument()
  })
})
