import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch } from '../test/utils'
import { conceptFixture, ontologyFixture, schemeFixture, vocabPageFixture } from '../test/vocabFixtures'
import { fetchConcept, fetchOntology, fetchScheme, listVocabularies, ontologyRdfUrl, schemeRdfUrl } from '.'

describe('API de vocabularios', () => {
  it('listVocabularies envía q y kind, y omite los vacíos', async () => {
    const page = vocabPageFixture()
    const fetchMock = mockFetch({ '/vocabularies': () => jsonResponse(page) })
    await expect(listVocabularies({ q: ' pru ', kind: 'skos_corp' })).resolves.toEqual(page)
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('q')).toBe('pru')
    expect(url.searchParams.get('kind')).toBe('skos_corp')
    await listVocabularies()
    expect(String(fetchMock.mock.calls[1][0])).toBe('http://api.test/vocabularies')
  })

  it('fetchOntology pide la ficha y, si se indica, ?version=', async () => {
    const fetchMock = mockFetch({ '/ontologies/onto-prueba': () => jsonResponse(ontologyFixture()) })
    await fetchOntology('onto-prueba')
    await fetchOntology('onto-prueba', '1.0.0')
    expect(String(fetchMock.mock.calls[0][0])).toBe('http://api.test/ontologies/onto-prueba')
    expect(String(fetchMock.mock.calls[1][0])).toBe('http://api.test/ontologies/onto-prueba?version=1.0.0')
  })

  it('fetchScheme y fetchConcept usan la ruta corporativa cuando corp es true', async () => {
    const fetchMock = mockFetch({
      '/schemes/esq-prueba': () => jsonResponse(schemeFixture()),
      '/schemes/corp/corp-prueba': () => jsonResponse(schemeFixture()),
      '/schemes/esq-prueba/concepts/concepto-a1': () => jsonResponse(conceptFixture()),
      '/schemes/corp/corp-prueba/concepts/c-1': () => jsonResponse(conceptFixture()),
    })
    await fetchScheme('esq-prueba', false)
    await fetchScheme('corp-prueba', true)
    await fetchConcept('esq-prueba', false, 'concepto-a1')
    await fetchConcept('corp-prueba', true, 'c-1')
    expect(fetchMock.mock.calls.map(([u]) => new URL(String(u)).pathname)).toEqual([
      '/schemes/esq-prueba',
      '/schemes/corp/corp-prueba',
      '/schemes/esq-prueba/concepts/concepto-a1',
      '/schemes/corp/corp-prueba/concepts/c-1',
    ])
  })

  it('construye las URL de descarga de RDF con VITE_API_BASE_URL', () => {
    expect(ontologyRdfUrl('onto-prueba', 'rdfxml')).toBe('http://api.test/ontologies/onto-prueba/rdf?format=rdfxml')
    expect(ontologyRdfUrl('onto-prueba', 'turtle', '1.0.0')).toBe(
      'http://api.test/ontologies/onto-prueba/rdf?format=turtle&version=1.0.0',
    )
    expect(schemeRdfUrl('trl', true, 'turtle')).toBe('http://api.test/schemes/corp/trl/rdf?format=turtle')
  })

  it('propaga el 404 como ApiError', async () => {
    mockFetch({})
    await expect(fetchScheme('no-existe', false)).rejects.toMatchObject({ name: 'ApiError', status: 404 })
  })
})
