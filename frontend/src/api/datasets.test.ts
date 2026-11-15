import { describe, expect, it } from 'vitest'
import { cardFixture, detailFixture, pageFixture, textResponse } from '../test/fixtures'
import { jsonResponse, mockFetch } from '../test/utils'
import { fetchDataset, fetchDatasetRdf, listDatasets } from '.'

describe('API del catálogo', () => {
  it('listDatasets envía q, domain y page_size, y omite los vacíos', async () => {
    const page = pageFixture([cardFixture()])
    const fetchMock = mockFetch({ '/datasets': () => jsonResponse(page) })

    await expect(listDatasets({ q: '  modbus ', domain: 'ot', pageSize: 100 })).resolves.toEqual(page)
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('q')).toBe('modbus')
    expect(url.searchParams.get('domain')).toBe('ot')
    expect(url.searchParams.get('page_size')).toBe('100')

    await listDatasets({ q: '' })
    expect(String(fetchMock.mock.calls[1][0])).toBe('http://api.test/datasets')
  })

  it('fetchDataset pide la ficha y, si se indica, ?version=', async () => {
    const fetchMock = mockFetch({ '/datasets/dataset-prueba': () => jsonResponse(detailFixture()) })

    await fetchDataset('dataset-prueba')
    await fetchDataset('dataset-prueba', '1.0.0')
    expect(String(fetchMock.mock.calls[0][0])).toBe('http://api.test/datasets/dataset-prueba')
    expect(String(fetchMock.mock.calls[1][0])).toBe('http://api.test/datasets/dataset-prueba?version=1.0.0')
  })

  it('fetchDatasetRdf pide el formato y devuelve el texto', async () => {
    const fetchMock = mockFetch({
      '/datasets/dataset-prueba/rdf': () => textResponse('# turtle de prueba', 'text/turtle'),
    })

    await expect(fetchDatasetRdf('dataset-prueba', 'turtle')).resolves.toBe('# turtle de prueba')
    const [url, init] = fetchMock.mock.calls[0]
    expect(new URL(String(url)).searchParams.get('format')).toBe('turtle')
    expect(new Headers(init?.headers).get('Accept')).toBe('text/turtle')
  })

  it('propaga el 404 como ApiError', async () => {
    mockFetch({})
    await expect(fetchDataset('no-existe')).rejects.toMatchObject({ name: 'ApiError', status: 404 })
  })
})
