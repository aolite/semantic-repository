/**
 * Textos y utilidades de la publicación de esquemas y ontologías (decisión
 * 50) que comparten los formularios y las pantallas.
 */
import type { OntologyIngestResult, SchemeDetail, SchemeIngestResult } from '../api'
import type { MenuItem } from '../components/PublishMenu'
import { getBaseUri } from '../config'

export type PublishKind = 'scheme' | 'ontology'

export type PublishResult =
  | { kind: 'scheme'; result: SchemeIngestResult }
  | { kind: 'ontology'; result: OntologyIngestResult }

/** Opciones del menú «Publicar recurso» (decisión 50 d). */
export type PublishOption = 'catalog' | 'dataset' | 'scheme' | 'ontology'

/** Opciones del menú «Publicar recurso», en el orden de la decisión 50 (d). */
export const PUBLISH_OPTIONS: MenuItem<PublishOption>[] = [
  { id: 'catalog', label: 'Nuevo catálogo' },
  { id: 'dataset', label: 'Nuevo dataset' },
  { id: 'scheme', label: 'Nuevo vocabulario' },
  { id: 'ontology', label: 'Nueva ontología' },
]

/**
 * Opciones del menú según el contexto: en la ficha de un catálogo (`fixed`)
 * no hay «Nuevo catálogo», porque los catálogos no agrupan otros catálogos
 * (solo el raíz lleva `dcat:catalog`; `semantic/uris.md`).
 */
export function publishOptions(fixed: boolean): MenuItem<PublishOption>[] {
  return fixed ? PUBLISH_OPTIONS.filter((option) => option.id !== 'catalog') : PUBLISH_OPTIONS
}

export const PUBLISH_TEXT = {
  catalogRequired: 'Elige el catálogo en el que se publica.',
  noCatalogs: 'Todavía no hay catálogos: crea uno antes de publicar.',
  unchanged: 'El RDF era idéntico al publicado: no ha cambiado nada.',
} as const

/** Aviso tras publicar un esquema o una versión de ontología. */
export function publishedNotice(published: PublishResult): string {
  if (!published.result.changed) return PUBLISH_TEXT.unchanged
  if (published.kind === 'scheme') {
    const n = published.result.concepts
    const concepts = n === 1 ? '1 concepto' : `${n} conceptos`
    return published.result.created ? `Esquema publicado con ${concepts}.` : `Esquema republicado con ${concepts}.`
  }
  return published.result.created
    ? `Versión ${published.result.version} de la ontología publicada.`
    : `Versión ${published.result.version} de la ontología sustituida.`
}

/** Los esquemas auxiliares (`vocab/dominio`, `vocab/tipo-dataset`) no se gestionan desde la aplicación. */
export function isManagedScheme(scheme: SchemeDetail): boolean {
  return scheme.kind !== 'auxiliary'
}

/** URI sin `BASE_URI` (`dataset/x/1.0.0`, `vocab/ot/c`…), más corta y legible que la completa. */
export function shortUri(uri: string): string {
  const base = getBaseUri()
  return base && uri.startsWith(base) ? uri.slice(base.length) : uri
}
