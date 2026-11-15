import { describe, expect, it } from 'vitest'
import { vocabCardFixture } from '../test/vocabFixtures'
import {
  compactIri,
  conceptsLabel,
  isLinkableIri,
  langRank,
  metricsLine,
  normalizeText,
  prefixLabel,
  versionLabel,
  vocabularyCount,
} from './labels'

describe('Textos de vocabularios', () => {
  it('añade los dos puntos al prefijo y usa [VERSIÓN] sin versión', () => {
    expect(prefixLabel('itot')).toBe('itot:')
    expect(prefixLabel('itot:')).toBe('itot:')
    expect(prefixLabel(null)).toBeNull()
    expect(versionLabel('1.2.0')).toBe('v1.2.0')
    expect(versionLabel(null)).toBe('[VERSIÓN]')
  })

  it('usa [N] para los esquemas sin conceptos', () => {
    expect(conceptsLabel(null)).toBe('[N] conceptos')
    expect(conceptsLabel(0)).toBe('[N] conceptos')
    expect(conceptsLabel(1)).toBe('1 concepto')
    expect(conceptsLabel(13)).toBe('13 conceptos')
  })

  it('compone la línea de métricas según el tipo', () => {
    expect(metricsLine(vocabCardFixture({ metrics: { classes: 1, properties: 1 } }))).toBe('1 clase · 1 propiedad')
    expect(metricsLine(vocabCardFixture({ metrics: null }))).toBe('Métricas sin calcular')
    expect(metricsLine(vocabCardFixture({ kind: 'external' }))).toBe('Externa · referencia')
    expect(metricsLine(vocabCardFixture({ kind: 'skos_domain', concepts: 13 }))).toBe('13 conceptos')
    expect(vocabularyCount(1)).toBe('1 vocabulario')
    expect(vocabularyCount(2)).toBe('2 vocabularios')
  })

  it('abrevia las relaciones conocidas y deja el resto', () => {
    expect(compactIri('http://www.w3.org/2000/01/rdf-schema#subClassOf')).toBe('rdfs:subClassOf')
    expect(compactIri('http://www.w3.org/2004/02/skos/core#closeMatch')).toBe('skos:closeMatch')
    expect(compactIri('http://www.w3.org/2002/07/owl#equivalentClass')).toBe('owl:equivalentClass')
    expect(compactIri('https://otra.test/rel')).toBe('https://otra.test/rel')
  })

  it('ordena idiomas, detecta IRIs enlazables y normaliza acentos', () => {
    expect(['en', 'fr', 'ca', 'es', null].sort((a, b) => langRank(a) - langRank(b))).toEqual(['es', 'ca', 'en', 'fr', null])
    expect(isLinkableIri('https://x.test/a')).toBe(true)
    expect(isLinkableIri('https://x.test/[QID]')).toBe(false)
    expect(isLinkableIri('urn:x')).toBe(false)
    expect(normalizeText('Concepto Á2')).toBe('concepto a2')
  })
})
