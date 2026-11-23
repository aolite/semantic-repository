import { apiRequest, apiRequestVoid, jsonBody } from './client'
import type {
  CatalogCreate,
  CatalogDetail,
  CatalogPage,
  CatalogUpdate,
  DatasetCreate,
  DatasetDetail,
} from './types'

function catalogPath(slug: string): string {
  return `/catalogs/${encodeURIComponent(slug)}`
}

/** `GET /catalogs`: catálogos (sin el raíz ni las bajas), con su número de datasets. */
export function listCatalogs(signal?: AbortSignal): Promise<CatalogPage> {
  return apiRequest<CatalogPage>('/catalogs', { signal })
}

/** `GET /catalogs/{slug}`: ficha del catálogo (410 con `GoneResponse` si se dio de baja). */
export function fetchCatalog(slug: string, signal?: AbortSignal): Promise<CatalogDetail> {
  return apiRequest<CatalogDetail>(catalogPath(slug), { signal })
}

/** `POST /catalogs` (editor o admin). */
export function createCatalog(body: CatalogCreate, token: string): Promise<CatalogDetail> {
  return apiRequest<CatalogDetail>('/catalogs', { method: 'POST', token, ...jsonBody(body) })
}

/** `PATCH /catalogs/{slug}` (editor o admin): solo cambian los campos presentes. */
export function updateCatalog(slug: string, body: CatalogUpdate, token: string): Promise<CatalogDetail> {
  return apiRequest<CatalogDetail>(catalogPath(slug), { method: 'PATCH', token, ...jsonBody(body) })
}

/** `DELETE /catalogs/{slug}` (editor o admin): baja de un catálogo vacío (409 si tiene datasets). */
export function withdrawCatalog(slug: string, token: string): Promise<void> {
  return apiRequestVoid(catalogPath(slug), { method: 'DELETE', token })
}

/** `POST /catalogs/{slug}/datasets` (editor o admin): dataset (serie sin versiones) en el catálogo. */
export function createDatasetInCatalog(catalog: string, body: DatasetCreate, token: string): Promise<DatasetDetail> {
  return apiRequest<DatasetDetail>(`${catalogPath(catalog)}/datasets`, { method: 'POST', token, ...jsonBody(body) })
}
