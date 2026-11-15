/**
 * Textos y colores de presentación que pone el frontend (no la API):
 * nombres y colores de los dominios, etiquetas cortas de formato, texto del
 * acceso y placeholders del prototipo.
 */
import type { AccessRights, DomainSlug, ResourceRef, ThemeRef } from '../api'

export interface DomainStyle {
  label: string
  /** Color de la muestra en la navegación. */
  swatch: string
  /** Fondo y texto de la etiqueta de dominio (tarjetas y ficha). */
  tagBg: string
  tagFg: string
}

/** Dominios del prototipo, en el orden de los chips del catálogo. */
export const DOMAINS: Record<DomainSlug, DomainStyle> = {
  it: { label: 'Seguridad IT', swatch: 'var(--domain-it)', tagBg: 'var(--domain-it-bg)', tagFg: 'var(--domain-it-fg)' },
  ot: { label: 'OT / ICS', swatch: 'var(--domain-ot)', tagBg: 'var(--domain-ot-bg)', tagFg: 'var(--domain-ot-fg)' },
  pqc: {
    label: 'PQC e identidad',
    swatch: 'var(--domain-pqc)',
    tagBg: 'var(--domain-pqc-bg)',
    tagFg: 'var(--domain-pqc-fg)',
  },
  ia: { label: 'IA adversaria', swatch: 'var(--domain-ai)', tagBg: 'var(--domain-ai-bg)', tagFg: 'var(--domain-ai-fg)' },
}

export const DOMAIN_SLUGS: DomainSlug[] = ['it', 'ot', 'pqc', 'ia']

export function isDomainSlug(value: string | null | undefined): value is DomainSlug {
  return value !== null && value !== undefined && (DOMAIN_SLUGS as string[]).includes(value)
}

/** Placeholders del prototipo para los campos que llegan `null`. */
export const PLACEHOLDERS = {
  license: '[LICENCIA]',
  contact: '[CONTACTO]',
  date: '[FECHA]',
  project: '[PROYECTO]',
} as const

/** Texto neutro para campos sin placeholder en el prototipo. */
export const NOT_STATED = 'Sin indicar'

/**
 * Etiquetas cortas de formato (tarjetas del prototipo: «PCAP · CSV · Parquet»,
 * «CSV · RDF», «NPZ · JSON»; ontologías: «Turtle · RDF/XML · JSON-LD»).
 * `text/turtle` se muestra «RDF» como en la tarjeta de datasets del prototipo.
 */
const FORMAT_LABELS: Record<string, string> = {
  'application/vnd.tcpdump.pcap': 'PCAP',
  'text/csv': 'CSV',
  'application/vnd.apache.parquet': 'Parquet',
  'application/json': 'JSON',
  'text/turtle': 'RDF',
  'application/ld+json': 'JSON-LD',
  'application/rdf+xml': 'RDF/XML',
}

/**
 * Etiqueta corta de un formato. Los tipos IANA desconocidos se muestran tal
 * cual; si no es un tipo IANA, la API manda el título de la distribución
 * (p. ej. «NPZ») y también se muestra tal cual.
 */
export function formatLabel(format: string): string {
  return FORMAT_LABELS[format.trim().toLowerCase()] ?? format
}

/** Línea de formatos y versión de la tarjeta: «PCAP · CSV · Parquet · v2.1.0». */
export function formatsLine(formats: string[], version: string | null): string {
  const labels = [...new Set(formats.map(formatLabel))]
  if (version) labels.push(`v${version}`)
  return labels.join(' · ')
}

const ACCESS_LABELS: Record<string, string> = {
  PUBLIC: 'Público',
  RESTRICTED: 'Restringido',
}

/**
 * Texto del acceso a partir de `code`. Los códigos sin traducción acordada se
 * muestran tal cual; sin `code`, la IRI.
 */
export function accessLabel(access: AccessRights | null): string | null {
  if (!access) return null
  if (!access.code) return access.uri
  return ACCESS_LABELS[access.code] ?? access.code
}

/** Etiqueta legible de un recurso enlazado: label, IRI o `fallback`. */
export function resourceLabel(ref: ResourceRef | null, fallback: string): string {
  return ref?.label ?? ref?.uri ?? fallback
}

/** Etiqueta de un tema: prefLabel o, si no está cargado, la IRI. */
export function themeLabel(theme: ThemeRef): string {
  return theme.label ?? theme.uri
}

/** Último segmento de una IRI (sin barra final). */
export function lastSegment(uri: string): string {
  const parts = uri.replace(/\/+$/, '').split('/')
  return parts[parts.length - 1] ?? uri
}

/** «1 recurso» / «N recursos». */
export function resourceCount(n: number): string {
  return n === 1 ? '1 recurso' : `${n} recursos`
}
