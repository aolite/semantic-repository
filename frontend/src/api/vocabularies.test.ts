import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch } from '../test/utils'
import { conceptFixture, ontologyFixture, schemeFixture, vocabPageFixture } from '../test/vocabFixtures'
import {
  externalOntologyRdfUrl,
  fetchConcept,
  fetchExternalOntology,
  replaceExternalOntology,
  fetchOntology,
  fetchScheme,
  listVocabularies,
  ontologyRdfUrl,
  publishOntology,
  publishScheme,
  schemeRdfUrl,
  updateOntology,
  updateScheme,
  withdrawOntology,
  withdrawScheme,
} from '.'
import { externalOntologyFixture, externalReplaceFixture, ontologyIngestFixture, schemeIngestFixture } from '../test/vocabFixtures'

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
    await listVocabularies({ domain: 'pqc' })
    expect(new URL(String(fetchMock.mock.calls[2][0])).searchParams.get('domain')).toBe('pqc')
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
    expect(ontologyRdfUrl('onto-prueba', 'rdfxml')).toBe('http://api.test/ontologies/onto-prueba/rdf?format=rdfxml&download=1')
    expect(ontologyRdfUrl('onto-prueba', 'turtle', '1.0.0')).toBe(
      'http://api.test/ontologies/onto-prueba/rdf?format=turtle&version=1.0.0&download=1',
    )
    expect(schemeRdfUrl('trl', true, 'turtle')).toBe('http://api.test/schemes/corp/trl/rdf?format=turtle&download=1')
  })

  it('listVocabularies envía ?catalog= (decisión 50)', async () => {
    const fetchMock = mockFetch({ '/vocabularies': () => jsonResponse(vocabPageFixture()) })
    await listVocabularies({ catalog: 'cat-a' })
    expect(new URL(String(fetchMock.mock.calls[0][0])).searchParams.get('catalog')).toBe('cat-a')
  })

  it('publishScheme y publishOntology mandan el RDF con su tipo, ?catalog= y el token', async () => {
    const fetchMock = mockFetch({
      '/schemes': () => jsonResponse(schemeIngestFixture(), 201),
      '/ontologies': () => jsonResponse(ontologyIngestFixture(), 201),
    })
    await expect(publishScheme('@prefix x: <y> .', 'text/turtle', 'cat-a', 'tk')).resolves.toEqual(schemeIngestFixture())
    await publishOntology('{}', 'application/ld+json', 'cat-b', 'tk')
    const [schemeCall, ontologyCall] = fetchMock.mock.calls
    expect(String(schemeCall[0])).toBe('http://api.test/schemes?catalog=cat-a')
    expect(schemeCall[1]?.method).toBe('POST')
    expect(schemeCall[1]?.headers).toMatchObject({ 'Content-Type': 'text/turtle', Authorization: 'Bearer tk' })
    expect(String(ontologyCall[0])).toBe('http://api.test/ontologies?catalog=cat-b')
    expect(ontologyCall[1]?.headers).toMatchObject({ 'Content-Type': 'application/ld+json' })
  })

  it('updateScheme, withdrawScheme, updateOntology y withdrawOntology usan PATCH y DELETE en su ruta', async () => {
    const fetchMock = mockFetch({
      '/schemes/corp/trl': () => new Response(null, { status: 204 }),
      '/schemes/ot': () => jsonResponse(schemeFixture()),
      '/ontologies/onto-prueba': (_u, init) =>
        init?.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(ontologyFixture()),
    })
    await updateScheme('ot', false, { title: 'T', catalog: 'cat-b' }, 'tk')
    await withdrawScheme('trl', true, 'tk')
    await updateOntology('onto-prueba', { catalog: 'cat-b' }, 'tk')
    await withdrawOntology('onto-prueba', 'tk')
    expect(fetchMock.mock.calls.map(([u, init]) => `${init?.method} ${new URL(String(u)).pathname}`)).toEqual([
      'PATCH /schemes/ot',
      'DELETE /schemes/corp/trl',
      'PATCH /ontologies/onto-prueba',
      'DELETE /ontologies/onto-prueba',
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ title: 'T', catalog: 'cat-b' })
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ catalog: 'cat-b' })
  })

  it('propaga el 404 como ApiError', async () => {
    mockFetch({})
    await expect(fetchScheme('no-existe', false)).rejects.toMatchObject({ name: 'ApiError', status: 404 })
  })

  describe('ontologías externas (decisión 51)', () => {
    it('fetchExternalOntology pide la ficha pública y externalOntologyRdfUrl añade la versión si se indica', async () => {
      const fetchMock = mockFetch({ '/ontologies/externas/ext': () => jsonResponse(externalOntologyFixture()) })
      await expect(fetchExternalOntology('ext')).resolves.toEqual(externalOntologyFixture())
      expect(String(fetchMock.mock.calls[0][0])).toBe('http://api.test/ontologies/externas/ext')
      expect(fetchMock.mock.calls[0][1]?.headers).not.toHaveProperty('Authorization')
      expect(externalOntologyRdfUrl('ext', 'turtle')).toBe('http://api.test/ontologies/externas/ext/rdf?format=turtle&download=1')
      expect(externalOntologyRdfUrl('ext', 'jsonld', 1)).toBe(
        'http://api.test/ontologies/externas/ext/rdf?format=jsonld&version=1&download=1',
      )
    })

    it('replaceExternalOntology manda multipart con el fichero y solo los campos con valor', async () => {
      const fetchMock = mockFetch({ '/ontologies/externas/ext/versions': () => jsonResponse(externalReplaceFixture(), 201) })
      const file = new File(['@prefix x: <https://externa.test/> .'], 'ext.ttl')
      const result = await replaceExternalOntology(
        'ext',
        file,
        'text/turtle',
        { title: ' Título ', prefix: 'ext', namespace: 'https://externa.test/onto#', description: '', version_notes: 'Notas' },
        'tk',
      )
      expect(result.number).toBe(3)
      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toBe('http://api.test/ontologies/externas/ext/versions')
      expect(init?.method).toBe('POST')
      expect(init?.headers).toMatchObject({ Authorization: 'Bearer tk' })
      // Sin `Content-Type`: lo pone el navegador con el `boundary` del multipart.
      expect(init?.headers).not.toHaveProperty('Content-Type')
      const body = init?.body as FormData
      expect(body).toBeInstanceOf(FormData)
      expect([...body.keys()].sort()).toEqual(['file', 'namespace', 'prefix', 'title', 'version_notes'])
      expect(body.get('title')).toBe('Título')
      const sent = body.get('file') as File
      expect(sent.name).toBe('ext.ttl')
      expect(sent.type).toBe('text/turtle')
    })
  })
})
