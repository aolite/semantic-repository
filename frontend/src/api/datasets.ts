import { apiRequest, apiRequestText, apiRequestVoid, jsonBody, withQuery } from './client'
import type {
  DatasetDetail,
  DatasetPage,
  DatasetUpdate,
  DomainSlug,
  DownloadLink,
  IngestResult,
  RdfFormat,
} from './types'

export interface ListDatasetsParams {
  /** Texto libre: título, descripción y temas. */
  q?: string
  domain?: DomainSlug
  /** Slug del catálogo (`catalogo/{slug}`, decisión 49). */
  catalog?: string
  page?: number
  /** Máximo 100 según el contrato. */
  pageSize?: number
}

/** `GET /datasets`: tarjetas del catálogo. */
export function listDatasets(params: ListDatasetsParams = {}, signal?: AbortSignal): Promise<DatasetPage> {
  const path = withQuery('/datasets', {
    q: params.q?.trim(),
    domain: params.domain,
    catalog: params.catalog,
    page: params.page,
    page_size: params.pageSize,
  })
  return apiRequest<DatasetPage>(path, { signal })
}

/** `GET /datasets/{slug}`: ficha de la versión actual o de `version`. */
export function fetchDataset(slug: string, version?: string | null, signal?: AbortSignal): Promise<DatasetDetail> {
  const path = withQuery(`/datasets/${encodeURIComponent(slug)}`, { version })
  return apiRequest<DatasetDetail>(path, { signal })
}

const RDF_MEDIA_TYPES: Record<RdfFormat, string> = {
  turtle: 'text/turtle',
  jsonld: 'application/ld+json',
}

/** `GET /datasets/{slug}/rdf`: RDF de la versión en Turtle o JSON-LD. */
export function fetchDatasetRdf(
  slug: string,
  format: RdfFormat,
  version?: string | null,
  signal?: AbortSignal,
): Promise<string> {
  const path = withQuery(`/datasets/${encodeURIComponent(slug)}/rdf`, { format, version })
  return apiRequestText(path, RDF_MEDIA_TYPES[format], { signal })
}

/**
 * `POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link`
 * (miembro o superior): enlace firmado de vida corta para descargar una
 * distribución `authenticated` sin poner el JWT en la URL.
 */
export function requestDownloadLink(slug: string, version: string, dist: string, token: string): Promise<DownloadLink> {
  const path = [
    '/datasets',
    encodeURIComponent(slug),
    'versions',
    encodeURIComponent(version),
    'distributions',
    encodeURIComponent(dist),
    'download-link',
  ].join('/')
  return apiRequest<DownloadLink>(path, { method: 'POST', token })
}

function datasetPath(slug: string): string {
  return `/datasets/${encodeURIComponent(slug)}`
}

/** `PATCH /datasets/{slug}` (editor o admin): metadatos de la serie; `catalog` la mueve de catálogo. */
export function updateDataset(slug: string, body: DatasetUpdate, token: string): Promise<DatasetDetail> {
  return apiRequest<DatasetDetail>(datasetPath(slug), { method: 'PATCH', token, ...jsonBody(body) })
}

/** `DELETE /datasets/{slug}` (editor o admin): baja del dataset; el backend elimina sus ficheros. */
export function withdrawDataset(slug: string, token: string): Promise<void> {
  return apiRequestVoid(datasetPath(slug), { method: 'DELETE', token })
}

/** Tipos de medio que admite `POST /datasets`. */
export type IngestMediaType = 'text/turtle' | 'application/ld+json'

/**
 * `POST /datasets?catalog=` (editor o admin): publica la serie con todas sus
 * versiones (RDF validado con SHACL por el backend). Así se publica una
 * versión nueva: las ya publicadas tienen que venir sin cambios.
 */
export function publishDatasetRdf(
  rdf: Blob | string,
  mediaType: IngestMediaType,
  catalog: string | null,
  token: string,
): Promise<IngestResult> {
  const path = withQuery('/datasets', { catalog })
  return apiRequest<IngestResult>(path, { method: 'POST', token, body: rdf, headers: { 'Content-Type': mediaType } })
}
