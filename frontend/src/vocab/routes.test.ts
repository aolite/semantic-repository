import { describe, expect, it } from 'vitest'
import { vocabCardsFixture } from '../test/vocabFixtures'
import {
  conceptRouteFromUri,
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
    expect(ontologyRouteFromUri('https://saref.test/core/')).toBeNull()
  })

  it('elige el destino de cada tarjeta: ficha, navegador o IRI oficial', () => {
    const [own, external, corp, domain] = vocabCardsFixture()
    expect(vocabularyHref(own)).toEqual({ href: '/ontologias/onto-prueba', external: false })
    expect(vocabularyHref(external)).toEqual({ href: 'https://externa.test/onto/', external: true })
    expect(vocabularyHref(corp)).toEqual({ href: '/vocabularios/corp/corp-prueba', external: false })
    expect(vocabularyHref(domain)).toEqual({ href: '/vocabularios/esq-prueba', external: false })
  })
})
