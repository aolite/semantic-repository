/**
 * Mensajes de los formularios de catálogos, datasets y versiones (decisión
 * 49) a partir de los errores de la API. Los textos son del frontend: el
 * prototipo no tiene estas pantallas.
 */
import { ApiError, type ConflictResponse, type GoneResponse, type IngestErrorResponse } from '../api'
import { lastSegment } from '../catalog/labels'

export type FormField = 'slug' | 'title' | 'description' | 'publisher_name' | 'catalog' | 'file'

export interface FormErrorInfo {
  /** Mensaje general del formulario. */
  message: string
  /** Campos que hay que marcar como no válidos, con su mensaje. */
  fields: Partial<Record<FormField, string>>
  /** Detalle adicional (incidencias SHACL, versiones afectadas…). */
  issues: string[]
}

export interface ErrorContext {
  /** Texto del 404 (p. ej. «El catálogo no existe.»). */
  notFound: string
  /** Texto si la API falla de otra forma. */
  fallback: string
}

const FORM_FIELDS: FormField[] = ['slug', 'title', 'description', 'publisher_name', 'catalog']

/** Máximo de incidencias que se listan bajo el mensaje. */
const MAX_ISSUES = 10

export const CRUD_TEXT = {
  offline: 'No se ha podido conectar con la API.',
  unauthorized: 'La sesión ha caducado o no es válida. Vuelve a iniciar sesión.',
  forbidden: 'Tu cuenta no tiene permiso para esta acción: hace falta el rol editor o admin.',
  slugTaken:
    'El slug ya está en uso o es de un recurso dado de baja (un slug dado de baja no se reutiliza). Elige otro.',
  slugInUse: 'Ya existe un recurso con ese slug. Elige otro.',
  slugWithdrawn: 'Ese slug es de un recurso dado de baja y no se reutiliza. Elige otro.',
  gone: 'El recurso se dio de baja.',
  tooLarge: 'El fichero supera el tamaño máximo que admite la API.',
  unsupported: 'Formato no admitido: sube un fichero Turtle (.ttl) o JSON-LD (.jsonld).',
  unavailable: 'El repositorio no está disponible ahora mismo. Inténtalo más tarde.',
  busy: 'El servidor está ocupado; inténtalo de nuevo en unos segundos.',
  invalidFields: 'Revisa los campos marcados.',
  invalidField: 'Valor no válido.',
  catalogHasDatasets:
    'El catálogo todavía tiene datasets. Muévelos a otro catálogo (desde «Editar» en su ficha) o dalos de baja antes.',
} as const

/** Mensaje de cada `IngestErrorResponse.kind`. */
export const INGEST_KIND_TEXT: Record<IngestErrorResponse['kind'], string> = {
  syntax: 'El RDF tiene errores de sintaxis.',
  structure: 'La estructura del RDF no es válida para una serie de dataset.',
  uri: 'Alguna URI no sigue el patrón del repositorio.',
  shacl: 'Los datos no cumplen las reglas de validación (SHACL).',
  limit: 'El RDF supera un límite de la ingesta (tamaño, número de tripletas o tiempo de validación).',
  catalog: 'El catálogo indicado no existe o se dio de baja.',
  version_removed:
    'Falta una versión ya publicada: el fichero tiene que incluir la serie con todas sus versiones publicadas, sin cambios.',
  version_immutable: 'Una versión ya publicada viene con otro contenido: las versiones publicadas no se pueden modificar.',
  withdrawn: 'Ese slug es de un recurso dado de baja y no se reutiliza.',
  catalog_conflict:
    'La serie ya está en otro catálogo. Para cambiarla de catálogo, usa «Editar» en la ficha del dataset.',
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** `IngestErrorResponse` del cuerpo de un error, si lo es. */
export function ingestError(error: unknown): IngestErrorResponse | null {
  if (!(error instanceof ApiError) || !isObject(error.body)) return null
  const body = error.body
  if (typeof body.kind !== 'string' || !(body.kind in INGEST_KIND_TEXT)) return null
  return body as unknown as IngestErrorResponse
}

/** Ficha mínima de un 410 (`GoneResponse`), si lo es. */
export function goneFromError(error: unknown): GoneResponse | null {
  if (!(error instanceof ApiError) || error.status !== 410 || !isObject(error.body)) return null
  const body = error.body
  if (typeof body.uri !== 'string') return null
  return {
    detail: typeof body.detail === 'string' ? body.detail : '',
    uri: body.uri,
    resource: body.resource === 'catalog' ? 'catalog' : 'dataset',
    title: typeof body.title === 'string' ? body.title : null,
    withdrawn_at: typeof body.withdrawn_at === 'string' ? body.withdrawn_at : null,
  }
}

/** `kind` de un 409 `ConflictResponse` del CRUD, si lo es. */
export function conflictKind(error: unknown): ConflictResponse['kind'] | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !isObject(error.body)) return null
  // `IngestErrorResponse` (409 de `POST /datasets`) también tiene `kind` (`withdrawn`), pero trae `issues`.
  if (Array.isArray(error.body.issues)) return null
  const kind = error.body.kind
  return kind === 'slug_in_use' || kind === 'withdrawn' || kind === 'catalog_not_empty' ? kind : null
}

/** URIs de las series de un 409 `ConflictResponse` `catalog_not_empty` (baja de un catálogo con datasets). */
export function conflictDatasets(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 409 || !isObject(error.body)) return []
  const datasets = error.body.datasets
  return Array.isArray(datasets) ? datasets.filter((d): d is string => typeof d === 'string') : []
}

function issueLines(body: IngestErrorResponse): string[] {
  const lines = (body.issues ?? []).map((issue) => {
    const where = issue.path ?? issue.focus_node
    return where ? `${issue.message} (${lastSegment(where)})` : issue.message
  })
  return lines.slice(0, MAX_ISSUES)
}

/** Errores de validación de FastAPI (`detail` con `loc` y `msg`) por campo del formulario. */
function validationFields(body: unknown): Partial<Record<FormField, string>> | null {
  if (!isObject(body) || !Array.isArray(body.detail)) return null
  const fields: Partial<Record<FormField, string>> = {}
  for (const item of body.detail) {
    if (!isObject(item) || !Array.isArray(item.loc)) continue
    const name = item.loc[item.loc.length - 1]
    if (typeof name === 'string' && (FORM_FIELDS as string[]).includes(name)) {
      fields[name as FormField] = CRUD_TEXT.invalidField
    }
  }
  return fields
}

/** Traduce un error de la API a mensajes del formulario. */
export function describeError(error: unknown, context: ErrorContext): FormErrorInfo {
  const info: FormErrorInfo = { message: context.fallback, fields: {}, issues: [] }
  if (!(error instanceof ApiError)) return info

  // 409 del CRUD (`ConflictResponse`): slug en uso, slug dado de baja o catálogo con datasets.
  const conflict = conflictKind(error)
  if (conflict === 'slug_in_use' || conflict === 'withdrawn') {
    info.message = conflict === 'slug_in_use' ? CRUD_TEXT.slugInUse : CRUD_TEXT.slugWithdrawn
    info.fields.slug = info.message
    return info
  }
  if (conflict === 'catalog_not_empty') {
    info.message = CRUD_TEXT.catalogHasDatasets
    return info
  }

  const ingest = ingestError(error)
  if (ingest) {
    info.message = INGEST_KIND_TEXT[ingest.kind]
    info.issues = issueLines(ingest)
    if (ingest.kind === 'catalog') info.fields.catalog = INGEST_KIND_TEXT.catalog
    if (ingest.kind === 'withdrawn') info.fields.slug = INGEST_KIND_TEXT.withdrawn
    return info
  }

  switch (error.status) {
    case 0:
      info.message = CRUD_TEXT.offline
      break
    case 401:
      info.message = CRUD_TEXT.unauthorized
      break
    case 403:
      info.message = CRUD_TEXT.forbidden
      break
    case 404:
      info.message = context.notFound
      break
    case 409:
      info.message = CRUD_TEXT.slugTaken
      info.fields.slug = CRUD_TEXT.slugTaken
      break
    case 410: {
      const gone = goneFromError(error)
      info.message = gone?.title ? `«${gone.title}» se dio de baja.` : CRUD_TEXT.gone
      break
    }
    case 413:
      info.message = CRUD_TEXT.tooLarge
      info.fields.file = CRUD_TEXT.tooLarge
      break
    case 415:
      info.message = CRUD_TEXT.unsupported
      info.fields.file = CRUD_TEXT.unsupported
      break
    case 422: {
      const fields = validationFields(error.body)
      info.message = CRUD_TEXT.invalidFields
      info.fields = fields ?? {}
      if (error.detail) info.issues = [error.detail]
      break
    }
    case 503:
      // Con `Retry-After`, otra escritura tiene el bloqueo del catálogo (QA-49-03): es pasajero.
      info.message = error.retryAfter !== null ? CRUD_TEXT.busy : CRUD_TEXT.unavailable
      break
  }
  return info
}
