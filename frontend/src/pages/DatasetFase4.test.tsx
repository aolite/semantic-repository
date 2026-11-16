import { screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DatasetDetail, FairSummary } from '../api'
import { DOWNLOAD_TEXT } from '../dataset/download'
import { FAIR_STATUS_TEXT } from '../dataset/fair'
import { startDownload } from '../lib/startDownload'
import { accessPublic, detailFixture, distributionFixture, fairFixture, textResponse, versionFixture } from '../test/fixtures'
import { jsonResponse, mockFetch, renderApp, tokenFixture, userFixture } from '../test/utils'

vi.mock('../lib/startDownload', () => ({ startDownload: vi.fn() }))

const PATH = '/datasets/dataset-prueba'
const LINK_PATH = `${PATH}/versions/2.1.0/distributions/a/download-link`

type Handler = Parameters<typeof mockFetch>[0][string]

function mockDataset(detail: DatasetDetail = detailFixture(), extra: Record<string, Handler> = {}) {
  return mockFetch({
    [PATH]: () => jsonResponse(detail),
    [`${PATH}/rdf`]: () => textResponse('# prueba-turtle', 'text/turtle'),
    ...extra,
  })
}

function withFair(fair: FairSummary | null): DatasetDetail {
  return detailFixture({ version: versionFixture({ fair }) })
}

async function renderDataset(route = PATH) {
  const result = renderApp(route)
  await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
  return result
}

function section(name: string) {
  return screen.getByRole('heading', { level: 2, name }).closest('section') as HTMLElement
}

beforeEach(() => {
  vi.mocked(startDownload).mockClear()
})

describe('Ficha de dataset · Evaluación FAIR', () => {
  it('muestra el total, el nivel de F-UJI y el desglose F/A/I/R de la API', async () => {
    mockDataset(withFair(fairFixture()))
    await renderDataset()
    const fair = section('Evaluación FAIR')

    expect(within(fair).getByText('v2.1.0')).toBeInTheDocument()
    expect(within(fair).getByText('41')).toBeInTheDocument()
    expect(within(fair).getByText('/ 100')).toBeInTheDocument()
    expect(within(fair).getByText('Madurez 1.75 / 3')).toBeInTheDocument()
    expect(
      within(fair).getByText('Puntuación calculada en backend sobre los metadatos y las distribuciones publicadas.'),
    ).toBeInTheDocument()

    const dims = within(within(fair).getByRole('list', { name: 'Puntuación por principio' })).getAllByRole('listitem')
    expect(dims.map((d) => d.textContent)).toEqual([
      'F · Findable11',
      'A · Accessible22',
      'I · Interoperable33',
      'R · Reusable44',
    ])
    // Sin las pistas de ejemplo del prototipo.
    expect(within(fair).queryByText(/URI persistente, metadatos ricos/)).not.toBeInTheDocument()
    expect(within(fair).queryByText('Disponible en la fase 4')).not.toBeInTheDocument()
  })

  it('rellena «Última evaluación» y «Evaluador» y enlaza el informe completo en la API', async () => {
    mockDataset(withFair(fairFixture()))
    await renderDataset()
    const fair = section('Evaluación FAIR')

    expect(within(fair).getByText(/Última evaluación:/)).toHaveTextContent(
      'Última evaluación: 2000-01-02 · Evaluador: evaluador-de-prueba 0.0.0',
    )
    expect(within(fair).getByText('2000-01-02').closest('time')).toHaveAttribute('dateTime', '2000-01-02T03:04:05Z')
    expect(within(fair).getByRole('link', { name: 'Ver informe completo de pruebas' })).toHaveAttribute(
      'href',
      'http://api.test/datasets/dataset-prueba/versions/2.1.0/fair/report',
    )
  })

  it('mantiene los placeholders [FECHA] y [MOTOR FAIR] y oculta el informe si la API no los da', async () => {
    mockDataset(withFair(fairFixture({ evaluated_at: null, evaluator: null, report_url: null, maturity: null })))
    await renderDataset()
    const fair = section('Evaluación FAIR')
    expect(within(fair).getByText(/Última evaluación:/)).toHaveTextContent(
      'Última evaluación: [FECHA] · Evaluador: [MOTOR FAIR]',
    )
    expect(within(fair).queryByRole('link')).not.toBeInTheDocument()
    expect(within(fair).getByText('Sin indicar')).toBeInTheDocument()
  })

  it.each([
    ['sin resumen (null)', null, FAIR_STATUS_TEXT.not_evaluated],
    ['not_evaluated', fairFixture({ status: 'not_evaluated', total: null }), FAIR_STATUS_TEXT.not_evaluated],
    ['pending', fairFixture({ status: 'pending', total: null }), FAIR_STATUS_TEXT.pending],
    ['running', fairFixture({ status: 'running', total: null }), FAIR_STATUS_TEXT.running],
    ['failed', fairFixture({ status: 'failed', total: null }), FAIR_STATUS_TEXT.failed],
  ])('estado %s: lo dice y no muestra puntuaciones', async (_name, fair, text) => {
    mockDataset(withFair(fair))
    await renderDataset()
    const panel = section('Evaluación FAIR')
    expect(within(panel).getByText(text)).toBeInTheDocument()
    expect(within(panel).queryByText('/ 100')).not.toBeInTheDocument()
    expect(within(panel).queryByRole('list')).not.toBeInTheDocument()
  })

  it('con una evaluación en curso sigue mostrando la última terminada', async () => {
    mockDataset(withFair(fairFixture({ status: 'running' })))
    await renderDataset()
    const panel = section('Evaluación FAIR')
    expect(within(panel).getByText(FAIR_STATUS_TEXT.running)).toBeInTheDocument()
    expect(within(panel).getByText('41')).toBeInTheDocument()
  })
})

describe('Ficha de dataset · Distribuciones', () => {
  function distributionsDetail() {
    return detailFixture({
      version: versionFixture({
        distributions: [
          distributionFixture('a'),
          distributionFixture('b', {
            title: 'Distribución B',
            access_rights: accessPublic,
            download: 'open',
          }),
          distributionFixture('c', {
            title: 'Distribución C',
            access_rights: { uri: 'http://publications.europa.eu/resource/authority/access-right/NON_PUBLIC', code: 'NON_PUBLIC' },
            download: 'metadata_only',
            download_url: null,
            byte_size: null,
            sha256: null,
          }),
          distributionFixture('d', { title: 'Distribución D', download: 'unavailable', download_url: null }),
        ],
      }),
    })
  }

  function row(name: string) {
    return within(section('Distribuciones')).getByRole('row', { name: new RegExp(name) })
  }

  it('tiene la columna «Acción» oculta visualmente y el ancla #distribuciones', async () => {
    mockDataset(distributionsDetail())
    await renderDataset()
    const panel = section('Distribuciones')
    expect(panel).toHaveAttribute('id', 'distribuciones')
    const headers = within(within(panel).getByRole('table')).getAllByRole('columnheader')
    expect(headers.map((h) => h.textContent)).toEqual(['Distribución', 'dcat:mediaType', 'Acceso', 'Acción'])
    expect(within(headers[3]).getByText('Acción')).toHaveClass('visually-hidden')
  })

  it('open: «Descargar» enlaza al fichero a través de la API', async () => {
    mockDataset(distributionsDetail())
    await renderDataset()
    const link = within(row('Distribución B')).getByRole('link', { name: 'Descargar Distribución B' })
    expect(link).toHaveAttribute('href', 'http://api.test/dataset/dataset-prueba/2.1.0/b/fichero')
  })

  it('metadata_only y unavailable: texto sin acción', async () => {
    mockDataset(distributionsDetail())
    await renderDataset()
    expect(within(row('Distribución C')).getByText(DOWNLOAD_TEXT.metadataOnly)).toBeInTheDocument()
    expect(within(row('Distribución C')).queryByRole('link')).not.toBeInTheDocument()
    expect(within(row('Distribución D')).getByText(DOWNLOAD_TEXT.unavailable)).toBeInTheDocument()
    expect(within(row('Distribución D')).queryByRole('button')).not.toBeInTheDocument()
  })

  it('no muestra «Solicitar», «Solicitar acceso» ni «Nueva versión»', async () => {
    mockDataset(distributionsDetail())
    await renderDataset()
    expect(screen.queryByText('Solicitar')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Solicitar acceso' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nueva versión' })).not.toBeInTheDocument()
  })

  it('authenticated sin sesión: «Iniciar sesión para descargar» lleva al login y vuelve a la ficha; con sesión descarga con enlace firmado', async () => {
    const fetchMock = mockDataset(distributionsDetail(), {
      '/auth/token': () => jsonResponse(tokenFixture({ access_token: 'token-x' })),
      '/auth/me': () => jsonResponse(userFixture()),
      [LINK_PATH]: () =>
        jsonResponse({
          url: 'http://uri.test/itot/dataset/dataset-prueba/2.1.0/a/fichero?token=firmado',
          expires_at: '2000-01-01T00:01:00Z',
        }),
    })
    const { user } = await renderDataset(`${PATH}?version=2.1.0`)

    expect(within(row('Distribución A')).queryByRole('button', { name: /Descargar/ })).not.toBeInTheDocument()
    await user.click(within(row('Distribución A')).getByRole('link', { name: 'Iniciar sesión para descargar Distribución A' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Iniciar sesión' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Usuario'), 'usuario-prueba')
    await user.type(screen.getByLabelText('Contraseña'), 'contrasena-prueba')
    await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))

    // Vuelve a la misma ficha y versión.
    await screen.findByRole('heading', { level: 1, name: 'Dataset de prueba' })
    const datasetCalls = fetchMock.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === PATH)
    expect(datasetCalls.at(-1)!.searchParams.get('version')).toBe('2.1.0')

    const button = await within(row('Distribución A')).findByRole('button', { name: 'Descargar Distribución A' })
    await user.click(button)

    await waitFor(() =>
      expect(startDownload).toHaveBeenCalledWith('http://api.test/dataset/dataset-prueba/2.1.0/a/fichero?token=firmado'),
    )
    const linkCall = fetchMock.mock.calls.find(([u]) => new URL(String(u)).pathname === LINK_PATH)!
    expect(linkCall[1]?.method).toBe('POST')
    expect(new Headers(linkCall[1]?.headers).get('Authorization')).toBe('Bearer token-x')
  })

  it.each([
    [401, DOWNLOAD_TEXT.expired],
    [403, DOWNLOAD_TEXT.forbidden],
    [500, DOWNLOAD_TEXT.failed],
  ])('con sesión, si el enlace firmado falla con %i lo explica', async (status, text) => {
    mockDataset(distributionsDetail(), {
      '/auth/token': () => jsonResponse(tokenFixture()),
      '/auth/me': () => jsonResponse(userFixture()),
      [LINK_PATH]: () => jsonResponse({ detail: 'error de prueba' }, status),
    })
    const { user } = await renderDataset()
    await user.click(within(row('Distribución A')).getByRole('link', { name: /Iniciar sesión para descargar/ }))
    await user.type(await screen.findByLabelText('Usuario'), 'usuario-prueba')
    await user.type(screen.getByLabelText('Contraseña'), 'contrasena-prueba')
    await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))

    const button = await within(await waitFor(() => row('Distribución A'))).findByRole('button', {
      name: 'Descargar Distribución A',
    })
    await user.click(button)
    expect(await within(row('Distribución A')).findByRole('alert')).toHaveTextContent(text)
    expect(startDownload).not.toHaveBeenCalled()
  })
})
