import { describe, expect, it } from 'vitest'
import { ApiError, type SavedQuery } from '../api'
import {
  resultCountLabel,
  saveErrorMessage,
  sortSavedQueries,
  sparqlErrorMessage,
  termText,
  toCsv,
} from './results'

describe('Resultados SPARQL', () => {
  it('cuenta en singular y en plural', () => {
    expect(resultCountLabel(0)).toBe('0 resultados')
    expect(resultCountLabel(1)).toBe('1 resultado')
    expect(resultCountLabel(5)).toBe('5 resultados')
  })

  it('pinta cada tipo de término', () => {
    expect(termText({ type: 'uri', value: 'http://uri.test/x' })).toBe('http://uri.test/x')
    expect(termText({ type: 'literal', value: 'hola', 'xml:lang': 'es' })).toBe('hola')
    expect(termText({ type: 'bnode', value: 'b0' })).toBe('_:b0')
    expect(termText(undefined)).toBe('')
  })

  it('genera CSV del W3C: cabecera sin «?», comillas dobladas, celdas vacías y CRLF', () => {
    const csv = toCsv({
      head: { vars: ['a', 'b'] },
      results: {
        bindings: [
          { a: { type: 'uri', value: 'http://uri.test/1' }, b: { type: 'literal', value: 'con, coma' } },
          { a: { type: 'bnode', value: 'x' } },
          { a: { type: 'literal', value: 'línea\nnueva' }, b: { type: 'literal', value: 'di "hola"' } },
        ],
      },
    })
    expect(csv).toBe('a,b\r\nhttp://uri.test/1,"con, coma"\r\n_:x,\r\n"línea\nnueva","di ""hola"""\r\n')
  })

  it('CSV de un ASK y de un resultado sin variables', () => {
    expect(toCsv({ head: {}, boolean: false })).toBe('false')
    expect(toCsv({ head: {} })).toBe('\r\n')
  })

  it('traduce los errores de /sparql', () => {
    expect(sparqlErrorMessage(new ApiError(400, 'x'))).toBe('La consulta no es válida.')
    expect(sparqlErrorMessage(new ApiError(400, 'x', 'Detalle.'))).toBe('La consulta no es válida: Detalle.')
    expect(sparqlErrorMessage(new ApiError(429, 'x', null, 5))).toContain('dentro de 5 s')
    expect(sparqlErrorMessage(new ApiError(0, 'x'))).toBe('No se ha podido conectar con la API.')
    expect(sparqlErrorMessage(new Error('x'))).toBe('No se ha podido ejecutar la consulta.')
  })

  it('traduce los errores al guardar', () => {
    expect(saveErrorMessage(new ApiError(413, 'x'))).toBe('La consulta supera el tamaño máximo permitido.')
    expect(saveErrorMessage(new ApiError(500, 'x'))).toBe('No se ha podido guardar la consulta.')
    expect(saveErrorMessage(new Error('x'))).toBe('No se ha podido guardar la consulta.')
  })

  it('ordena primero las de referencia y respeta el orden de la API en cada grupo', () => {
    const q = (id: string, kind: SavedQuery['kind']): SavedQuery => ({
      id,
      title: id,
      hint: null,
      query: 'ASK {}',
      kind,
      created_at: null,
      updated_at: null,
    })
    const sorted = sortSavedQueries([q('p2', 'personal'), q('r1', 'reference'), q('p1', 'personal'), q('r0', 'reference')])
    expect(sorted.map((s) => s.id)).toEqual(['r1', 'r0', 'p2', 'p1'])
  })
})
