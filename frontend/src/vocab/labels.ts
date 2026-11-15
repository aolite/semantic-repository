/**
 * Textos y colores de presentación de las pantallas de vocabularios (los pone
 * el frontend, no la API): nombres y colores de cada tipo y estado, líneas de
 * métricas y placeholders del prototipo.
 */
import type { VocabularyCard, VocabularyKind, VocabularyStatus } from '../api'

export interface KindStyle {
  /** Etiqueta de la tarjeta (singular), p. ej. «Ontología propia». */
  label: string
  /** Etiqueta de las estadísticas, los chips y la navegación (plural). */
  short: string
  /** Muestra de la navegación lateral («Tipos de vocabulario»). */
  swatch: string
  tagBg: string
  tagFg: string
}

/** Tipos de vocabulario del prototipo, en su orden. */
export const KINDS: Record<VocabularyKind, KindStyle> = {
  own: {
    label: 'Ontología propia',
    short: 'Ontologías propias',
    swatch: 'var(--kind-own)',
    tagBg: 'var(--kind-own-bg)',
    tagFg: 'var(--kind-own-fg)',
  },
  external: {
    label: 'Ontología externa',
    short: 'Ontologías externas',
    swatch: 'var(--kind-external)',
    tagBg: 'var(--kind-external-bg)',
    tagFg: 'var(--kind-external-fg)',
  },
  skos_corp: {
    label: 'SKOS corporativo',
    short: 'SKOS corporativos',
    swatch: 'var(--kind-corp)',
    tagBg: 'var(--kind-corp-bg)',
    tagFg: 'var(--kind-corp-fg)',
  },
  skos_domain: {
    label: 'SKOS de dominio',
    short: 'SKOS de dominio',
    swatch: 'var(--kind-domain)',
    tagBg: 'var(--kind-domain-bg)',
    tagFg: 'var(--kind-domain-fg)',
  },
}

export const KIND_ORDER: VocabularyKind[] = ['own', 'external', 'skos_corp', 'skos_domain']

export const STATUSES: Record<VocabularyStatus, { label: string; className: string }> = {
  published: { label: 'Publicada', className: 'status--published' },
  draft: { label: 'Borrador', className: 'status--draft' },
  referenced: { label: 'Referenciada', className: 'status--referenced' },
}

/** Placeholders del prototipo para los campos que llegan `null`. */
export const VOCAB_PLACEHOLDERS = {
  version: '[VERSIÓN]',
  authors: '[AUTORES]',
  repository: '[REPOSITORIO GIT]',
  responsible: '[RESPONSABLE]',
  count: '[N]',
} as const

/** Prefijo VANN con los dos puntos del prototipo («itot:»). */
export function prefixLabel(prefix: string | null): string | null {
  if (!prefix) return null
  return prefix.endsWith(':') ? prefix : `${prefix}:`
}

/** «v1.2.0» o el placeholder si no hay versión. */
export function versionLabel(version: string | null): string {
  return version ? `v${version}` : VOCAB_PLACEHOLDERS.version
}

/** «1 concepto» / «N conceptos»; sin conceptos, «[N] conceptos» como el prototipo. */
export function conceptsLabel(n: number | null): string {
  if (!n) return `${VOCAB_PLACEHOLDERS.count} conceptos`
  return n === 1 ? '1 concepto' : `${n} conceptos`
}

/** Línea de métricas del pie de la tarjeta, según el tipo. */
export function metricsLine(card: VocabularyCard): string {
  switch (card.kind) {
    case 'own':
      return card.metrics
        ? `${plural(card.metrics.classes, 'clase', 'clases')} · ${plural(card.metrics.properties, 'propiedad', 'propiedades')}`
        : 'Métricas sin calcular'
    case 'external':
      return 'Externa · referencia'
    default:
      return conceptsLabel(card.concepts)
  }
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

/** «1 vocabulario» / «N vocabularios». */
export function vocabularyCount(n: number): string {
  return plural(n, 'vocabulario', 'vocabularios')
}

const KNOWN_PREFIXES: [string, string][] = [
  ['http://www.w3.org/2000/01/rdf-schema#', 'rdfs:'],
  ['http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf:'],
  ['http://www.w3.org/2002/07/owl#', 'owl:'],
  ['http://www.w3.org/2004/02/skos/core#', 'skos:'],
]

/** Abrevia las IRIs de RDF, RDFS, OWL y SKOS (p. ej. `rdfs:subClassOf`); el resto, tal cual. */
export function compactIri(iri: string): string {
  for (const [ns, prefix] of KNOWN_PREFIXES) {
    if (iri.startsWith(ns)) return prefix + iri.slice(ns.length)
  }
  return iri
}

const LANG_ORDER = ['es', 'ca', 'en']

/** Orden de idiomas de la ficha de concepto: es, ca, en y después el resto. */
export function langRank(lang: string | null): number {
  const i = lang ? LANG_ORDER.indexOf(lang) : -1
  return i === -1 ? LANG_ORDER.length : i
}

/**
 * Indica si una IRI se puede enlazar: http(s) y sin placeholders del
 * prototipo (`[QID]`…).
 */
export function isLinkableIri(iri: string): boolean {
  return /^https?:\/\//.test(iri) && !/[[\]\s]/.test(iri)
}

/** Normaliza para buscar sin distinguir mayúsculas ni acentos. */
export function normalizeText(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}
