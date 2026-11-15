import { describe, expect, it } from 'vitest'
import { accessLabel, formatLabel, formatsLine, lastSegment, resourceCount, resourceLabel } from './labels'

describe('Etiquetas del catálogo', () => {
  it.each([
    ['application/vnd.tcpdump.pcap', 'PCAP'],
    ['text/csv', 'CSV'],
    ['application/vnd.apache.parquet', 'Parquet'],
    ['application/json', 'JSON'],
    ['text/turtle', 'RDF'],
    ['NPZ', 'NPZ'],
    ['application/x-desconocido', 'application/x-desconocido'],
  ])('formatLabel(%s) = %s', (format, label) => {
    expect(formatLabel(format)).toBe(label)
  })

  it('compone formatos y versión sin repetir etiquetas', () => {
    expect(formatsLine(['application/vnd.tcpdump.pcap', 'text/csv', 'text/csv'], '2.1.0')).toBe('PCAP · CSV · v2.1.0')
    expect(formatsLine([], null)).toBe('')
  })

  it('traduce el acceso a partir de code', () => {
    expect(accessLabel({ uri: 'x', code: 'RESTRICTED' })).toBe('Restringido')
    expect(accessLabel({ uri: 'x', code: 'PUBLIC' })).toBe('Público')
    expect(accessLabel({ uri: 'x', code: 'NON_PUBLIC' })).toBe('NON_PUBLIC')
    expect(accessLabel({ uri: 'http://otra/iri', code: null })).toBe('http://otra/iri')
    expect(accessLabel(null)).toBeNull()
  })

  it('usa el placeholder cuando el recurso es null', () => {
    expect(resourceLabel(null, '[LICENCIA]')).toBe('[LICENCIA]')
    expect(resourceLabel({ uri: 'http://x/y', label: null }, '[LICENCIA]')).toBe('http://x/y')
  })

  it('cuenta recursos en singular y plural', () => {
    expect(resourceCount(1)).toBe('1 recurso')
    expect(resourceCount(0)).toBe('0 recursos')
    expect(resourceCount(3)).toBe('3 recursos')
  })

  it('extrae el último segmento de una IRI', () => {
    expect(lastSegment('http://uri.test/itot/dataset/serie/')).toBe('serie')
  })
})
