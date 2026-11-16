import { describe, expect, it } from 'vitest'
import { fairFixture } from '../test/fixtures'
import { FAIR_DIMENSIONS, fairDate, fairStatus, fairWidth } from './fair'

describe('Presentación FAIR', () => {
  it('usa las etiquetas del prototipo para F, A, I y R', () => {
    expect(FAIR_DIMENSIONS.map((d) => d.label)).toEqual([
      'F · Findable',
      'A · Accessible',
      'I · Interoperable',
      'R · Reusable',
    ])
  })

  it('sin resumen, el estado es «sin evaluar»', () => {
    expect(fairStatus(null)).toBe('not_evaluated')
    expect(fairStatus(fairFixture({ status: 'failed' }))).toBe('failed')
  })

  it('limita el ancho de las barras a 0-100 %', () => {
    expect(fairWidth(55)).toBe('55%')
    expect(fairWidth(140)).toBe('100%')
    expect(fairWidth(-3)).toBe('0%')
    expect(fairWidth(null)).toBe('0%')
    expect(fairWidth(Number.NaN)).toBe('0%')
  })

  it('muestra la fecha ISO como AAAA-MM-DD y lo demás tal cual', () => {
    expect(fairDate('2000-01-02T03:04:05Z')).toBe('2000-01-02')
    expect(fairDate('ayer')).toBe('ayer')
  })
})
