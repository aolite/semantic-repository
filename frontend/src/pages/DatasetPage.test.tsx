import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DatasetDetail } from '../api'
import { detailFixture, metadataFixture, oldVersionFixture, textResponse, versionFixture } from '../test/fixtures'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'

const PATH = '/datasets/dataset-prueba'

function mockDataset(detail: (url: URL) => DatasetDetail | Response = () => detailFixture()) {
  return mockFetch({
    [PATH]: (url) => {
      const result = detail(new URL(url))
      return result instanceof Response ? result : jsonResponse(result)
    },
    [`${PATH}/rdf`]: (url) => {
      const format = new URL(url).searchParams.get('format')
      return format === 'jsonld'
        ? textResponse('{"@id": "prueba-jsonld"}', 'application/ld+json')
        : textResponse('# prueba-turtle', 'text/turtle')
    },
  })
}

async function renderDataset(route = PATH) {
  const result = renderApp(route)
  await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
  return result
}

function section(name: string) {
  return screen.getByRole('heading', { level: 2, name }).closest('section, aside') as HTMLElement
}

function field(container: HTMLElement, term: string) {
  return within(container).getByText(term, { selector: 'dt' }).nextElementSibling as HTMLElement
}

describe('Ficha de dataset', () => {
  it('muestra migas, etiquetas, título y URI persistente', async () => {
    mockDataset()
    await renderDataset()

    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByRole('link', { name: 'Catálogo' })).toHaveAttribute('href', '/')
    expect(within(crumbs).getByText('OT / ICS')).toBeInTheDocument()
    expect(within(crumbs).getByText('Dataset')).toHaveAttribute('aria-current', 'page')

    expect(screen.getByText('dcat:Dataset')).toBeInTheDocument()
    expect(screen.getByText('Acceso restringido')).toBeInTheDocument()
    expect(screen.getByText('v2.1.0 · actual')).toBeInTheDocument()
    expect(screen.getByText('http://uri.test/itot/dataset/dataset-prueba')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nueva versión' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Solicitar acceso' })).not.toBeInTheDocument()
    expect(screen.queryByText('Dataset sintético')).not.toBeInTheDocument()
  })

  it('marca la ficha en la navegación lateral como parte del catálogo', async () => {
    mockDataset()
    await renderDataset()
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByRole('link', { name: 'Catálogo' })).toHaveAttribute('aria-current', 'true')
  })

  it('copia la URI al portapapeles y lo anuncia', async () => {
    mockDataset()
    const { user } = await renderDataset()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()

    await user.click(screen.getByRole('button', { name: 'Copiar URI' }))
    expect(writeText).toHaveBeenCalledWith('http://uri.test/itot/dataset/dataset-prueba')
    expect(await screen.findByText('URI copiada')).toBeInTheDocument()
  })

  it('marca los datasets sintéticos', async () => {
    mockDataset(() => detailFixture({ synthetic: true, version: versionFixture({ synthetic: true }) }))
    await renderDataset()
    expect(screen.getByText('Dataset sintético')).toBeInTheDocument()
  })

  it('muestra descripción, palabras clave y versionado', async () => {
    mockDataset()
    await renderDataset()

    expect(within(section('Descripción')).getByText('Palabras clave: clave-a, clave-b')).toBeInTheDocument()
    const versioning = section('Versionado')
    expect(field(versioning, 'dcat:version')).toHaveTextContent('2.1.0')
    expect(field(versioning, 'dct:issued (versión)')).toHaveTextContent('[FECHA]')
    expect(within(field(versioning, 'dcat:previousVersion')).getByRole('link')).toHaveAttribute(
      'href',
      `${PATH}?version=2.0.0`,
    )
    expect(within(field(versioning, 'dcat:inSeries')).getByRole('link', { name: 'dataset-prueba' })).toHaveAttribute(
      'href',
      PATH,
    )
    expect(within(versioning).getByText('Notas de prueba de la 2.1.0.', { selector: 'p' })).toBeInTheDocument()
  })

  it('enlaza cada versión del historial con ?version= y marca la actual', async () => {
    mockDataset()
    await renderDataset()

    const versioning = section('Versionado')
    expect(within(versioning).getByRole('heading', { level: 3, name: 'Historial de versiones' })).toBeInTheDocument()
    const current = within(versioning).getByRole('link', { name: 'Versión 2.1.0' })
    expect(current).toHaveAttribute('href', PATH)
    expect(current).toHaveAttribute('aria-current', 'page')
    expect(within(versioning).getByRole('link', { name: 'Versión 2.0.0' })).toHaveAttribute('href', `${PATH}?version=2.0.0`)
    expect(within(versioning).getByRole('link', { name: 'Versión 1.0.0' })).toHaveAttribute('href', `${PATH}?version=1.0.0`)
    expect(within(versioning).getAllByText('Actual')).toHaveLength(1)
    expect(within(versioning).getAllByText('Sustituida')).toHaveLength(2)
  })

  it('pinta las distribuciones en una tabla con encabezados y sin columna Acción', async () => {
    mockDataset()
    await renderDataset()

    const table = within(section('Distribuciones')).getByRole('table')
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Distribución', 'dcat:mediaType', 'Acceso'])
    const row = within(table).getByRole('row', { name: /Distribución A/ })
    expect(within(row).getByRole('rowheader')).toHaveTextContent('Distribución A')
    expect(within(row).getByText('text/csv')).toBeInTheDocument()
    expect(within(row).getByText('Restringido')).toBeInTheDocument()
  })

  it('muestra la cadena PROV-O del origen a la versión', async () => {
    mockDataset()
    await renderDataset()

    const steps = within(section('Procedencia')).getAllByRole('listitem')
    expect(steps.map((s) => s.textContent)).toEqual([
      'prov:ActivityActividad origen',
      'prov:EntityEntidad intermedia',
      'prov:ActivityActividad final',
      'prov:EntityEste dataset · v2.1.0',
    ])
    expect(within(section('Procedencia')).getByText('prov:wasAssociatedWith · Agente de prueba')).toBeInTheDocument()
  })

  it('cambia entre Turtle y JSON-LD pidiendo /rdf con el formato', async () => {
    const fetchMock = mockDataset()
    const { user } = await renderDataset()

    const rdf = section('Descripción RDF')
    const group = within(rdf).getByRole('group', { name: 'Serialización' })
    const turtle = within(group).getByRole('button', { name: 'Turtle' })
    const jsonld = within(group).getByRole('button', { name: 'JSON-LD' })
    expect(turtle).toHaveAttribute('aria-pressed', 'true')
    expect(await within(rdf).findByText('# prueba-turtle')).toBeInTheDocument()

    await user.click(jsonld)
    expect(jsonld).toHaveAttribute('aria-pressed', 'true')
    expect(turtle).toHaveAttribute('aria-pressed', 'false')
    expect(await within(rdf).findByText('{"@id": "prueba-jsonld"}')).toBeInTheDocument()

    const formats = fetchMock.mock.calls
      .map(([u]) => new URL(String(u)))
      .filter((u) => u.pathname === `${PATH}/rdf`)
      .map((u) => u.searchParams.get('format'))
    expect(formats).toEqual(['turtle', 'jsonld'])
  })

  it('muestra la Evaluación FAIR como disponible en la fase 4, sin puntuaciones', async () => {
    mockDataset()
    await renderDataset()
    const fair = section('Evaluación FAIR')
    expect(within(fair).getByText('Disponible en la fase 4')).toBeInTheDocument()
    expect(within(fair).queryByText(/\/ 100/)).not.toBeInTheDocument()
  })

  it('muestra los placeholders del prototipo cuando los metadatos llegan null', async () => {
    mockDataset()
    await renderDataset()

    const meta = section('Metadatos DCAT-AP')
    expect(field(meta, 'dct:publisher')).toHaveTextContent('Publicador de prueba')
    expect(field(meta, 'dcat:contactPoint')).toHaveTextContent('[CONTACTO]')
    expect(field(meta, 'dct:license')).toHaveTextContent('[LICENCIA]')
    expect(field(meta, 'dct:accessRights')).toHaveTextContent('Restringido (vocabulario EU Access Right)')
    expect(field(meta, 'dct:issued · dct:modified')).toHaveTextContent('[FECHA] · [FECHA]')
    expect(field(meta, 'dct:isReferencedBy')).toHaveTextContent('[PROYECTO]')
    expect(field(meta, 'dcat:theme')).toHaveTextContent('Tema A')
    expect(field(meta, 'dct:conformsTo')).toHaveTextContent('Ontología de prueba')
  })

  it('usa los valores de la API cuando existen', async () => {
    mockDataset(() =>
      detailFixture({
        version: versionFixture({
          metadata: metadataFixture({
            license: { uri: 'http://licencia.test/x', label: 'Licencia de prueba' },
            issued: '2000-01-01',
          }),
        }),
      }),
    )
    await renderDataset()
    const meta = section('Metadatos DCAT-AP')
    expect(field(meta, 'dct:license')).toHaveTextContent('Licencia de prueba')
    expect(field(meta, 'dct:issued · dct:modified')).toHaveTextContent('2000-01-01 · [FECHA]')
  })

  it('muestra una versión antigua con ?version= y sus secciones vacías sin inventar datos', async () => {
    const fetchMock = mockDataset((url) =>
      url.searchParams.get('version') === '1.0.0' ? detailFixture({ version: oldVersionFixture() }) : detailFixture(),
    )
    await renderDataset(`${PATH}?version=1.0.0`)

    expect(String(fetchMock.mock.calls[0][0])).toBe(`http://api.test${PATH}?version=1.0.0`)
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement
    expect(within(header).getByText('v1.0.0')).toBeInTheDocument()
    expect(screen.queryByText(/· actual/)).not.toBeInTheDocument()
    expect(screen.getByText('http://uri.test/itot/dataset/dataset-prueba/1.0.0')).toBeInTheDocument()

    expect(within(section('Distribuciones')).queryByRole('table')).not.toBeInTheDocument()
    expect(within(section('Distribuciones')).getByText('Esta versión no declara distribuciones.')).toBeInTheDocument()
    expect(within(section('Procedencia')).getByText('Esta versión no declara procedencia.')).toBeInTheDocument()
    expect(field(section('Metadatos DCAT-AP'), 'dcat:theme')).toHaveTextContent('Sin temas en esta versión')
    expect(within(section('Descripción')).getByText(/sin palabras clave/)).toBeInTheDocument()

    const versioning = section('Versionado')
    expect(field(versioning, 'dcat:previousVersion')).toHaveTextContent('Ninguna')
    expect(within(versioning).getByRole('link', { name: 'Versión 1.0.0' })).toHaveAttribute('aria-current', 'page')
    expect(within(versioning).getByRole('link', { name: 'Versión 2.1.0' })).not.toHaveAttribute('aria-current')

    await waitFor(() => {
      const rdfCall = fetchMock.mock.calls.map(([u]) => new URL(String(u))).find((u) => u.pathname === `${PATH}/rdf`)
      expect(rdfCall?.searchParams.get('version')).toBe('1.0.0')
    })
  })

  it('muestra «Dataset no encontrado» si la API responde 404', async () => {
    mockFetch({})
    renderApp('/datasets/no-existe')
    expect(await screen.findByRole('heading', { level: 1, name: 'Dataset no encontrado' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver al catálogo' })).toHaveAttribute('href', '/')
  })

  it('muestra un error accesible si la API falla', async () => {
    mockDataset(() => jsonResponse({ detail: 'Service Unavailable' }, 503))
    renderApp(PATH)
    expect(await screen.findByRole('alert')).toHaveTextContent('No se ha podido cargar el dataset.')
  })
})
