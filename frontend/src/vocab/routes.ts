/**
 * Rutas del frontend para ontologías, esquemas y conceptos, y su deducción a
 * partir de las URIs persistentes (`semantic/uris.md`), relativas a
 * `VITE_BASE_URI`. Si la URI no sigue el patrón, no hay ruta (null).
 */
import type { VocabularyCard } from '../api'
import { getBaseUri } from '../config'

const SLUG = '[a-z0-9]+(?:-[a-z0-9]+)*'
const VERSION = '(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)'

/** Esquemas auxiliares que no son navegables (no se listan en Vocabularios). */
const RESERVED_SCHEMES = new Set(['corp', 'dominio', 'tipo-dataset'])

/** Ficha de ontología: `/ontologias/{slug}` y, para versiones antiguas, `?version=`. */
export function ontologyRoute(slug: string, version?: string | null): string {
  const base = `/ontologias/${encodeURIComponent(slug)}`
  return version ? `${base}?version=${encodeURIComponent(version)}` : base
}

/**
 * Ficha de una ontología externa (decisión 51): `/ontologias/externas/{slug}`
 * y, para una versión, `?version={n}`. Destino del 303 de `onto/externas/…`.
 */
export function externalOntologyRoute(slug: string, version?: number | string | null): string {
  const base = `/ontologias/externas/${encodeURIComponent(slug)}`
  return version ? `${base}?version=${encodeURIComponent(String(version))}` : base
}

/** Navegador SKOS: `/vocabularios/{slug}` o `/vocabularios/corp/{slug}`, con `?concepto=`. */
export function schemeRoute(slug: string, corp: boolean, concept?: string | null): string {
  const base = `/vocabularios/${corp ? 'corp/' : ''}${encodeURIComponent(slug)}`
  return concept ? `${base}?concepto=${encodeURIComponent(concept)}` : base
}

function relative(uri: string): string | null {
  const base = getBaseUri()
  if (!base || !uri.startsWith(base)) return null
  return uri.slice(base.length)
}

/** Ruta del navegador para la URI de un concepto (`vocab/{esquema}/{c}` o `vocab/corp/{esquema}/{c}`). */
export function conceptRouteFromUri(uri: string): string | null {
  const rel = relative(uri)
  if (rel === null) return null
  const corp = new RegExp(`^vocab/corp/(${SLUG})/(${SLUG})$`).exec(rel)
  if (corp) return schemeRoute(corp[1], true, corp[2])
  const domain = new RegExp(`^vocab/(${SLUG})/(${SLUG})$`).exec(rel)
  if (domain && !RESERVED_SCHEMES.has(domain[1])) return schemeRoute(domain[1], false, domain[2])
  return null
}

/** Ruta del navegador para la URI de un esquema. */
export function schemeRouteFromUri(uri: string): string | null {
  const rel = relative(uri)
  if (rel === null) return null
  const corp = new RegExp(`^vocab/corp/(${SLUG})$`).exec(rel)
  if (corp) return schemeRoute(corp[1], true)
  const domain = new RegExp(`^vocab/(${SLUG})$`).exec(rel)
  if (domain && !RESERVED_SCHEMES.has(domain[1])) return schemeRoute(domain[1], false)
  return null
}

/**
 * Ruta de la ficha para la URI de una ontología propia o de una de sus
 * versiones (`owl:versionIRI`), o de una versión de ontología externa
 * (`onto/externas/{slug}/{n}`, decisión 51).
 */
export function ontologyRouteFromUri(uri: string): string | null {
  const rel = relative(uri)
  if (rel === null) return null
  const external = new RegExp(`^onto/externas/(${SLUG})(?:/([1-9][0-9]*))?$`).exec(rel)
  if (external) return externalOntologyRoute(external[1], external[2])
  const match = new RegExp(`^onto/(${SLUG})(?:/(${VERSION}))?$`).exec(rel)
  if (!match || match[1] === 'externas') return null
  return ontologyRoute(match[1], match[2])
}

/** Ruta de la ficha para la URI de un dataset o de una de sus versiones (`dataset/{slug}[/{version}]`). */
export function datasetRouteFromUri(uri: string): string | null {
  const rel = relative(uri)
  if (rel === null) return null
  const match = new RegExp(`^dataset/(${SLUG})(?:/(${VERSION}))?$`).exec(rel)
  if (!match) return null
  const base = `/datasets/${encodeURIComponent(match[1])}`
  return match[2] ? `${base}?version=${encodeURIComponent(match[2])}` : base
}

/**
 * Ruta del frontend para la URI de un recurso del repositorio: dataset (o
 * versión), ontología (o versión), esquema o concepto. Null si no sigue el
 * patrón (`semantic/uris.md`).
 */
export function resourceRouteFromUri(uri: string): string | null {
  return datasetRouteFromUri(uri) ?? ontologyRouteFromUri(uri) ?? schemeRouteFromUri(uri) ?? conceptRouteFromUri(uri)
}

/**
 * Destino de una tarjeta de vocabulario. Las ontologías externas con `slug`
 * van a su ficha (decisión 51); sin `slug` (sin prefijo), a su IRI oficial
 * (`external: true`).
 */
export function vocabularyHref(card: VocabularyCard): { href: string; external: boolean } {
  if (!card.slug) return { href: card.uri, external: true }
  if (card.kind === 'external') return { href: externalOntologyRoute(card.slug), external: false }
  if (card.kind === 'own') return { href: ontologyRoute(card.slug), external: false }
  return { href: schemeRoute(card.slug, card.kind === 'skos_corp'), external: false }
}
