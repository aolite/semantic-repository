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

/** Ruta de la ficha para la URI de una ontología propia o de una de sus versiones (`owl:versionIRI`). */
export function ontologyRouteFromUri(uri: string): string | null {
  const rel = relative(uri)
  if (rel === null) return null
  const match = new RegExp(`^onto/(${SLUG})(?:/(${VERSION}))?$`).exec(rel)
  if (!match || match[1] === 'externas') return null
  return ontologyRoute(match[1], match[2])
}

/**
 * Destino de una tarjeta de vocabulario. Las ontologías externas no tienen
 * ficha propia: enlazan a su IRI oficial (`external: true`).
 */
export function vocabularyHref(card: VocabularyCard): { href: string; external: boolean } {
  if (card.kind === 'external' || !card.slug) return { href: card.uri, external: true }
  if (card.kind === 'own') return { href: ontologyRoute(card.slug), external: false }
  return { href: schemeRoute(card.slug, card.kind === 'skos_corp'), external: false }
}
