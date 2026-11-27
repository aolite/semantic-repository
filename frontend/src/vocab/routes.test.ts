import { describe, expect, it } from 'vitest'
import { vocabCardsFixture } from '../test/vocabFixtures'
import {
  conceptRouteFromUri,
  datasetRouteFromUri,
  externalOntologyRoute,
  resourceRouteFromUri,
  ontologyRoute,
  ontologyRouteFromUri,
  schemeRoute,
  schemeRouteFromUri,
  vocabularyHref,
} from './routes'

const BASE = 'http://uri.test/itot/'

describe('Rutas de vocabularios', () => {
  it('construye las rutas de ficha y navegador', () => {
    expect(ontologyRoute('itot')).toBe('/ontologias/itot')
    expect(ontologyRoute('itot', '1.1.0')).toBe('/ontologias/itot?version=1.1.0')
    expect(externalOntologyRoute('saref')).toBe('/ontologias/externas/saref')
    expect(externalOntologyRoute('saref', 3)).toBe('/ontologias/externas/saref?version=3')
    expect(schemeRoute('ot', false)).toBe('/vocabularios/ot')
    expect(schemeRoute('trl', true, 'trl-1')).toBe('/vocabularios/corp/trl?concepto=trl-1')
  })

  it('deduce la ruta de un concepto de dominio o corporativo a partir de VITE_BASE_URI', () => {
    expect(conceptRouteFromUri(`${BASE}vocab/ot/modbus-tcp`)).toBe('/vocabularios/ot?concepto=modbus-tcp')
    expect(conceptRouteFromUri(`${BASE}vocab/corp/trl/trl-1`)).toBe('/vocabularios/corp/trl?concepto=trl-1')
  })

  it('no enlaza esquemas auxiliares, esquemas como conceptos ni URIs ajenas', () => {
    expect(conceptRouteFromUri(`${BASE}vocab/corp/trl`)).toBeNull()
    expect(conceptRouteFromUri(`${BASE}vocab/dominio/ot`)).toBeNull()
    expect(conceptRouteFromUri(`${BASE}vocab/tipo-dataset/sintetico`)).toBeNull()
    expect(conceptRouteFromUri('https://otro.test/itot/vocab/ot/modbus-tcp')).toBeNull()
    expect(conceptRouteFromUri(`${BASE}vocab/ot/modbus-tcp/extra`)).toBeNull()
  })

  it('deduce la ruta de un esquema', () => {
    expect(schemeRouteFromUri(`${BASE}vocab/ot`)).toBe('/vocabularios/ot')
    expect(schemeRouteFromUri(`${BASE}vocab/corp/trl`)).toBe('/vocabularios/corp/trl')
    expect(schemeRouteFromUri(`${BASE}vocab/dominio`)).toBeNull()
  })

  it('deduce la ficha de una ontología o de una de sus versiones', () => {
    expect(ontologyRouteFromUri(`${BASE}onto/itot`)).toBe('/ontologias/itot')
    expect(ontologyRouteFromUri(`${BASE}onto/itot/1.2.0`)).toBe('/ontologias/itot?version=1.2.0')
    expect(ontologyRouteFromUri(`${BASE}onto/itot#Clase`)).toBeNull()
    expect(ontologyRouteFromUri(`${BASE}onto/externas`)).toBeNull()
    // Decisión 51: la serie y las versiones de una externa van a su ficha.
    expect(ontologyRouteFromUri(`${BASE}onto/externas/saref`)).toBe('/ontologias/externas/saref')
    expect(ontologyRouteFromUri(`${BASE}onto/externas/saref/2`)).toBe('/ontologias/externas/saref?version=2')
    expect(ontologyRouteFromUri(`${BASE}onto/externas/saref/0`)).toBeNull()
    expect(ontologyRouteFromUri('https://saref.test/core/')).toBeNull()
  })

  it('deduce la ficha de un dataset o de una de sus versiones (usos del 409 in_use)', () => {
    expect(datasetRouteFromUri(`${BASE}dataset/d-1`)).toBe('/datasets/d-1')
    expect(datasetRouteFromUri(`${BASE}dataset/d-1/2.0.0`)).toBe('/datasets/d-1?version=2.0.0')
    expect(datasetRouteFromUri(`${BASE}dataset/d-1/2.0.0/dist`)).toBeNull()
    expect(datasetRouteFromUri('https://otro.test/dataset/d-1')).toBeNull()
  })

  it('resourceRouteFromUri elige la ruta según el tipo de URI', () => {
    expect(resourceRouteFromUri(`${BASE}dataset/d-1/1.0.0`)).toBe('/datasets/d-1?version=1.0.0')
    expect(resourceRouteFromUri(`${BASE}onto/itot/1.0.0`)).toBe('/ontologias/itot?version=1.0.0')
    expect(resourceRouteFromUri(`${BASE}vocab/ot`)).toBe('/vocabularios/ot')
    expect(resourceRouteFromUri(`${BASE}vocab/corp/trl/trl-1`)).toBe('/vocabularios/corp/trl?concepto=trl-1')
    expect(resourceRouteFromUri(`${BASE}catalogo/x`)).toBeNull()
  })

  it('elige el destino de cada tarjeta: ficha, navegador o IRI oficial', () => {
    const [own, external, corp, domain] = vocabCardsFixture()
    expect(vocabularyHref(own)).toEqual({ href: '/ontologias/onto-prueba', external: false })
    expect(vocabularyHref(external)).toEqual({ href: 'https://externa.test/onto/', external: true })
    expect(vocabularyHref(corp)).toEqual({ href: '/vocabularios/corp/corp-prueba', external: false })
    expect(vocabularyHref(domain)).toEqual({ href: '/vocabularios/esq-prueba', external: false })
    // Decisión 51: una externa con slug va a su ficha.
    expect(vocabularyHref({ ...external, slug: 'ext' })).toEqual({ href: '/ontologias/externas/ext', external: false })
  })
})
