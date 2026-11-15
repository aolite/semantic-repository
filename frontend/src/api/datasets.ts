import { apiRequest, apiRequestText, withQuery } from './client'
import type { DatasetDetail, DatasetPage, DomainSlug, RdfFormat } from './types'

export interface ListDatasetsParams {
  /** Texto libre: título, descripción y temas. */
  q?: string
  domain?: DomainSlug
  page?: number
  /** Máximo 100 según el contrato. */
  pageSize?: number
}

/** `GET /datasets`: tarjetas del catálogo. */
export function listDatasets(params: ListDatasetsParams = {}, signal?: AbortSignal): Promise<DatasetPage> {
  const path = withQuery('/datasets', {
    q: params.q?.trim(),
    domain: params.domain,
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
