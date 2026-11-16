import { describe, expect, it } from 'vitest'
import { catalogSearch, readCatalogParams, writeCatalogParams } from './urlState'

const params = (query: string) => new URLSearchParams(query)

describe('Estado del Catálogo en la URL', () => {
  it('lee los valores por defecto sin parámetros', () => {
    expect(readCatalogParams(params(''))).toEqual({ q: '', domain: 'all', type: 'all', page: 1 })
  })

  it('lee q, dominio, tipo y página', () => {
    expect(readCatalogParams(params('q=%20modbus%20&dominio=pqc&tipo=vocabularios&pagina=4'))).toEqual({
      q: 'modbus',
      domain: 'pqc',
      type: 'vocab',
      page: 4,
    })
    expect(readCatalogParams(params('tipo=datasets')).type).toBe('dataset')
  })

  it('ignora valores desconocidos o fuera de rango', () => {
    expect(readCatalogParams(params('dominio=xx&tipo=todo&pagina=0'))).toEqual({
      q: '',
      domain: 'all',
      type: 'all',
      page: 1,
    })
    expect(readCatalogParams(params('pagina=abc')).page).toBe(1)
    expect(readCatalogParams(params('pagina=1.5')).page).toBe(1)
    expect(readCatalogParams(params('pagina=99999999')).page).toBe(1)
  })

  it('no escribe los valores por defecto', () => {
    expect(writeCatalogParams(params('dominio=ot&pagina=2'), { domain: 'all', page: 1 }).toString()).toBe('')
  })

  it('vuelve a la página 1 al cambiar un filtro, salvo que se indique la página', () => {
    expect(writeCatalogParams(params('pagina=3'), { domain: 'it' }).toString()).toBe('dominio=it')
    expect(writeCatalogParams(params('pagina=3'), { q: 'x' }).toString()).toBe('q=x')
    expect(writeCatalogParams(params('pagina=3'), { type: 'dataset' }).toString()).toBe('tipo=datasets')
    // Mismo valor: no es un cambio de filtro.
    expect(writeCatalogParams(params('dominio=it&pagina=3'), { domain: 'it' }).toString()).toBe('dominio=it&pagina=3')
    expect(writeCatalogParams(params('q=x'), { q: 'y', page: 2 }).toString()).toBe('q=y&pagina=2')
  })

  it('conserva parámetros ajenos y recorta la búsqueda', () => {
    expect(writeCatalogParams(params('otro=1'), { q: '  a b ' }).toString()).toBe('otro=1&q=a+b')
  })

  it('catalogSearch devuelve «?…» o cadena vacía', () => {
    expect(catalogSearch(params('dominio=ia'), { page: 2 })).toBe('?dominio=ia&pagina=2')
    expect(catalogSearch(params('pagina=2'), { page: 1 })).toBe('')
  })
})
