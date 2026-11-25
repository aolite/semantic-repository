/**
 * Validación en el cliente de los formularios de catálogos y datasets, con
 * los límites de los esquemas `CatalogCreate` y `DatasetCreate` del OpenAPI.
 * El backend vuelve a validar todo (y con SHACL): esto solo adelanta los
 * errores evidentes.
 */
import type { IngestMediaType } from '../api'
import type { FormField } from './errors'

/** Patrón de los slugs (`semantic/uris.md`). */
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

export const LIMITS = { slug: 200, title: 300, description: 5000, publisher_name: 300 } as const

export const VALIDATION_TEXT = {
  required: 'Este campo es obligatorio.',
  slug: 'Solo minúsculas sin acentos, dígitos y guiones, sin guion al principio ni al final.',
  file: 'Elige un fichero Turtle (.ttl) o JSON-LD (.jsonld).',
} as const

export interface ResourceValues {
  slug: string
  title: string
  description: string
  publisher_name: string
}

export type FieldErrors = Partial<Record<FormField, string>>

/**
 * Errores del formulario. `requireSlug` al crear; `requirePublisher` en los
 * catálogos (en la serie el publicador es opcional en el contrato).
 */
export function validateResource(
  values: ResourceValues,
  { requireSlug, requirePublisher }: { requireSlug: boolean; requirePublisher: boolean },
): FieldErrors {
  const errors: FieldErrors = {}
  if (requireSlug) {
    const slug = values.slug.trim()
    if (!slug) errors.slug = VALIDATION_TEXT.required
    else if (!SLUG_PATTERN.test(slug) || slug.length > LIMITS.slug) errors.slug = VALIDATION_TEXT.slug
  }
  if (!values.title.trim()) errors.title = VALIDATION_TEXT.required
  if (!values.description.trim()) errors.description = VALIDATION_TEXT.required
  if (requirePublisher && !values.publisher_name.trim()) errors.publisher_name = VALIDATION_TEXT.required
  return errors
}

/** Tipo de medio de `POST /datasets` según la extensión del fichero; null si no se reconoce. */
export function mediaTypeForFile(name: string): IngestMediaType | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.ttl')) return 'text/turtle'
  if (lower.endsWith('.jsonld') || lower.endsWith('.json')) return 'application/ld+json'
  return null
}
