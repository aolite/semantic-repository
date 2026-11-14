import { afterEach, describe, expect, it, vi } from 'vitest'
import { getApiBaseUrl, getSparqlEndpointUrl, SPARQL_URL_PLACEHOLDER } from './config'

describe('config', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('añade la barra que falte a VITE_BASE_URI antes de "sparql"', () => {
    vi.stubEnv('VITE_BASE_URI', 'http://uri.test/itot')
    expect(getSparqlEndpointUrl()).toBe('http://uri.test/itot/sparql')
  })

  it('usa el placeholder del prototipo si no hay VITE_BASE_URI', () => {
    vi.stubEnv('VITE_BASE_URI', '')
    expect(getSparqlEndpointUrl()).toBe(SPARQL_URL_PLACEHOLDER)
  })

  it('quita la barra final de VITE_API_BASE_URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test/')
    expect(getApiBaseUrl()).toBe('http://api.test')
  })
})
