import { apiRequest, apiRequestVoid, apiUrl, jsonBody, withQuery } from './client'
import type { IngestMediaType } from './datasets'
import type {
  ConceptDetail,
  DomainSlug,
  OntologyDetail,
  OntologyIngestResult,
  OntologyUpdate,
  SchemeDetail,
  SchemeIngestResult,
  SchemeUpdate,
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
  /** Solo las ontologías propias y los esquemas de ese catálogo (decisión 50). */
  catalog?: string
}

/** `GET /vocabularies`: tarjetas de ontologías y esquemas, con el recuento por tipo. */
export function listVocabularies(params: ListVocabulariesParams = {}, signal?: AbortSignal): Promise<VocabularyPage> {
  const path = withQuery('/vocabularies', {
    q: params.q?.trim(),
    kind: params.kind,
    domain: params.domain,
    catalog: params.catalog,
  })
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

/* Decisión 50: publicar, editar, mover y dar de baja esquemas y ontologías (editor o admin). */

/**
 * `POST /schemes?catalog=`: publica (o republica) un esquema SKOS en Turtle o
 * JSON-LD en el catálogo. También es «Importar SKOS».
 */
export function publishScheme(
  rdf: Blob | string,
  mediaType: IngestMediaType,
  catalog: string | null,
  token: string,
): Promise<SchemeIngestResult> {
  return apiRequest<SchemeIngestResult>(withQuery('/schemes', { catalog }), {
    method: 'POST',
    token,
    body: rdf,
    headers: { 'Content-Type': mediaType },
  })
}

/** `PATCH /schemes/{slug}` o `/schemes/corp/{slug}`: título, descripción y publicador en español; `catalog` lo mueve. */
export function updateScheme(slug: string, corp: boolean, body: SchemeUpdate, token: string): Promise<SchemeDetail> {
  return apiRequest<SchemeDetail>(schemePath(slug, corp), { method: 'PATCH', token, ...jsonBody(body) })
}

/** `DELETE /schemes/{slug}` o `/schemes/corp/{slug}`: baja del esquema con sus conceptos (409 `in_use`). */
export function withdrawScheme(slug: string, corp: boolean, token: string): Promise<void> {
  return apiRequestVoid(schemePath(slug, corp), { method: 'DELETE', token })
}

/** `POST /ontologies?catalog=`: publica una versión de ontología en Turtle o JSON-LD en el catálogo. */
export function publishOntology(
  rdf: Blob | string,
  mediaType: IngestMediaType,
  catalog: string | null,
  token: string,
): Promise<OntologyIngestResult> {
  return apiRequest<OntologyIngestResult>(withQuery('/ontologies', { catalog }), {
    method: 'POST',
    token,
    body: rdf,
    headers: { 'Content-Type': mediaType },
  })
}

/** `PATCH /ontologies/{slug}`: mueve la ontología de catálogo (sus metadatos van en cada versión, inmutable). */
export function updateOntology(slug: string, body: OntologyUpdate, token: string): Promise<OntologyDetail> {
  return apiRequest<OntologyDetail>(`/ontologies/${encodeURIComponent(slug)}`, {
    method: 'PATCH',
    token,
    ...jsonBody(body),
  })
}

/** `DELETE /ontologies/{slug}`: baja de la ontología con todas sus versiones (409 `in_use`). */
export function withdrawOntology(slug: string, token: string): Promise<void> {
  return apiRequestVoid(`/ontologies/${encodeURIComponent(slug)}`, { method: 'DELETE', token })
}
