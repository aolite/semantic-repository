import { apiRequest, apiUrl, withQuery } from './client'
import type {
  ConceptDetail,
  DomainSlug,
  OntologyDetail,
  SchemeDetail,
  VocabRdfFormat,
  VocabularyKind,
  VocabularyPage,
} from './types'

export interface ListVocabulariesParams {
  /** Texto libre: nombre, prefijo o espacio de nombres. */
  q?: string
  kind?: VocabularyKind
  /** Solo las tarjetas con ese dominio (esquemas de dominio). */
  domain?: DomainSlug
}

/** `GET /vocabularies`: tarjetas de ontologías y esquemas, con el recuento por tipo. */
export function listVocabularies(params: ListVocabulariesParams = {}, signal?: AbortSignal): Promise<VocabularyPage> {
  const path = withQuery('/vocabularies', { q: params.q?.trim(), kind: params.kind, domain: params.domain })
  return apiRequest<VocabularyPage>(path, { signal })
}

/** `GET /ontologies/{slug}`: ficha de la versión actual o de `version`. */
export function fetchOntology(slug: string, version?: string | null, signal?: AbortSignal): Promise<OntologyDetail> {
  const path = withQuery(`/ontologies/${encodeURIComponent(slug)}`, { version })
  return apiRequest<OntologyDetail>(path, { signal })
}

/** URL de descarga de `GET /ontologies/{slug}/rdf?format=` con `download=1` (Content-Disposition: attachment). */
export function ontologyRdfUrl(slug: string, format: VocabRdfFormat, version?: string | null): string {
  return apiUrl(withQuery(`/ontologies/${encodeURIComponent(slug)}/rdf`, { format, version, download: 1 }))
}

/** Ruta de un esquema en la API: `/schemes/{slug}` o `/schemes/corp/{slug}`. */
function schemePath(slug: string, corp: boolean): string {
  return `/schemes/${corp ? 'corp/' : ''}${encodeURIComponent(slug)}`
}

/** `GET /schemes/{slug}` o `/schemes/corp/{slug}`: esquema con su árbol de conceptos. */
export function fetchScheme(slug: string, corp: boolean, signal?: AbortSignal): Promise<SchemeDetail> {
  return apiRequest<SchemeDetail>(schemePath(slug, corp), { signal })
}

/** URL de descarga de `GET /schemes/…/rdf?format=` con `download=1`. */
export function schemeRdfUrl(slug: string, corp: boolean, format: VocabRdfFormat): string {
  return apiUrl(withQuery(`${schemePath(slug, corp)}/rdf`, { format, download: 1 }))
}

/** `GET /schemes/…/concepts/{concept}`: detalle de un concepto y los recursos que lo usan. */
export function fetchConcept(
  slug: string,
  corp: boolean,
  concept: string,
  signal?: AbortSignal,
): Promise<ConceptDetail> {
  return apiRequest<ConceptDetail>(`${schemePath(slug, corp)}/concepts/${encodeURIComponent(concept)}`, { signal })
}
