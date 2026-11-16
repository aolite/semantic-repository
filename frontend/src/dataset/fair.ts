/**
 * Textos y colores de la sección «Evaluación FAIR» y de la barra FAIR de las
 * tarjetas. Las puntuaciones y el nivel de madurez salen tal cual de la API
 * (F-UJI); aquí solo hay presentación.
 */
import type { FairStatus, FairSummary } from '../api'

export type FairDimensionKey = 'findable' | 'accessible' | 'interoperable' | 'reusable'

/** Principios FAIR con la etiqueta y el color del prototipo. */
export const FAIR_DIMENSIONS: { key: FairDimensionKey; label: string; color: string }[] = [
  { key: 'findable', label: 'F · Findable', color: 'var(--fair-f)' },
  { key: 'accessible', label: 'A · Accessible', color: 'var(--fair-a)' },
  { key: 'interoperable', label: 'I · Interoperable', color: 'var(--fair-i)' },
  { key: 'reusable', label: 'R · Reusable', color: 'var(--fair-r)' },
]

/** Texto del prototipo bajo el nivel de madurez. */
export const FAIR_SCORE_NOTE = 'Puntuación calculada en backend sobre los metadatos y las distribuciones publicadas.'

/** Placeholder del prototipo cuando la API no da el evaluador. */
export const FAIR_ENGINE_PLACEHOLDER = '[MOTOR FAIR]'

/**
 * Textos de los estados sin puntuación nueva. **No están en el prototipo**
 * (solo muestra una evaluación terminada): son una propuesta del frontend.
 */
export const FAIR_STATUS_TEXT: Record<Exclude<FairStatus, 'done'>, string> = {
  not_evaluated: 'Esta versión todavía no tiene evaluación FAIR.',
  pending: 'La evaluación FAIR de esta versión está en cola.',
  running: 'La evaluación FAIR de esta versión está en curso.',
  failed: 'La última evaluación FAIR no se ha podido completar.',
}

/** Estado efectivo: sin resumen, «sin evaluar». */
export function fairStatus(fair: FairSummary | null): FairStatus {
  return fair?.status ?? 'not_evaluated'
}

/** Ancho de una barra (0-100 %) a partir de una puntuación de la API. */
export function fairWidth(score: number | null): string {
  if (score === null || !Number.isFinite(score)) return '0%'
  return `${Math.min(100, Math.max(0, score))}%`
}

/**
 * Fecha de la evaluación (`AAAA-MM-DD`), como el resto de fechas de la
 * ficha. Si no es ISO 8601, se muestra tal cual.
 */
export function fairDate(iso: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : iso
}
