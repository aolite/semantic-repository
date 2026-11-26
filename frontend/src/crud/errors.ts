/**
 * Mensajes de los formularios de catálogos, datasets y versiones (decisión
 * 49), y de esquemas y ontologías (decisión 50), a partir de los errores de
 * la API. Los textos son del frontend: el prototipo no tiene estas pantallas.
 */
import {
  ApiError,
  type ConflictResponse,
  type GoneResponse,
  type IngestErrorKind,
  type IngestErrorResponse,
  type UsageRef,
} from '../api'
import { lastSegment } from '../catalog/labels'
import { shortUri } from './publish'

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
  /**
   * Textos propios del recurso para algunos `IngestErrorResponse.kind` (p. ej.
   * `catalog_conflict` de un esquema, que se mueve desde su ficha).
   */
  ingestText?: Partial<Record<IngestErrorKind, string>>
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
    'El catálogo todavía tiene datasets, vocabularios u ontologías. Muévelos a otro catálogo (desde su ficha) o dalos de baja antes.',
  inUse:
    'No se puede dar de baja: lo usan recursos publicados. Antes hay que dar de baja los recursos que lo usan (las versiones publicadas no cambian).',
  notManaged:
    'Esta acción no está disponible para este recurso: una ontología externa solo se sustituye entera («Sustituir ontología» en su ficha) y un esquema auxiliar solo cambia con sus ficheros y la carga semántica.',
} as const

/** Mensaje de cada `IngestErrorResponse.kind`. */
export const INGEST_KIND_TEXT: Record<IngestErrorKind, string> = {
  syntax: 'El RDF tiene errores de sintaxis.',
  structure: 'La estructura del RDF no es válida para el recurso que se publica.',
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
  prefix_withdrawn:
    'El prefijo VANN (vann:preferredNamespacePrefix) era de un recurso dado de baja y no se reutiliza. Usa otro prefijo.',
  prefix_in_use:
    'El prefijo VANN (vann:preferredNamespacePrefix) ya lo usa otro recurso publicado. Usa otro prefijo.',
  concepts_removed:
    'Faltan conceptos que ya estaban publicados en el esquema. Un concepto no se quita: se retira marcándolo con owl:deprecated (y sus sustitutos con dct:isReplacedBy).',
  concept_reactivated:
    'Un concepto retirado (owl:deprecated) vuelve a estar activo: reactivar conceptos retirados no está previsto.',
  replacement: 'Algún sustituto (dct:isReplacedBy) no es un concepto vivo de este esquema o de otro publicado.',
  deprecated_theme:
    'La versión usa temas (dcat:theme) que son conceptos retirados. Cámbialos por sus sustitutos, si los tienen.',
  unknown_theme:
    'La versión usa temas (dcat:theme) del repositorio que no son conceptos de un esquema publicado (no existen o su esquema se dio de baja).',
  version_exists: 'Otra persona acaba de sustituir esta ontología; recarga la ficha y vuelve a intentarlo.',
}

/** Textos de los formularios de esquemas (decisión 50). */
export const SCHEME_INGEST_TEXT: Partial<Record<IngestErrorKind, string>> = {
  catalog_conflict:
    'El esquema ya está en otro catálogo. Para cambiarlo de catálogo, usa «Editar» en su ficha del Navegador SKOS.',
  withdrawn: 'Esa URI es de un esquema dado de baja y no se reutiliza.',
}

/** Textos de los formularios de ontologías (decisión 50). */
export const ONTOLOGY_INGEST_TEXT: Partial<Record<IngestErrorKind, string>> = {
  catalog_conflict:
    'La ontología ya está en otro catálogo. Para cambiarla de catálogo, usa «Mover de catálogo» en su ficha.',
  withdrawn: 'Esa URI es de una ontología dada de baja y no se reutiliza.',
}

/** Textos de «Sustituir ontología» de una ontología externa (decisión 51). */
export const EXTERNAL_INGEST_TEXT: Partial<Record<IngestErrorKind, string>> = {
  structure:
    'El fichero no declara la ontología con su IRI oficial (owl:Ontology) o algún campo del formulario no es válido.',
  uri: 'El fichero describe recursos con URIs del repositorio: una ontología externa no puede usarlas.',
  shacl: 'Los metadatos de la versión no cumplen las reglas de validación (SHACL).',
}

/**
 * Campos del formulario señalados en un 422 `structure` de la sustitución de
 * una externa (decisión 51): el backend pone el nombre del campo en
 * `issues[].path`. Solo se devuelven los de `fields`, con su mensaje.
 */
export function ingestFieldIssues<F extends string>(error: unknown, fields: readonly F[]): Partial<Record<F, string>> {
  const body = ingestError(error)
  const result: Partial<Record<F, string>> = {}
  if (!body || body.kind !== 'structure' || !Array.isArray(body.issues)) return result
  for (const issue of body.issues) {
    const path = issue.path
    if (typeof path === 'string' && (fields as readonly string[]).includes(path) && !result[path as F]) {
      result[path as F] = issue.message || CRUD_TEXT.invalidField
    }
  }
  return result
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * `IngestErrorResponse` del cuerpo de un error, si lo es: un `kind` conocido
 * o, si el backend añade uno nuevo, cualquier `kind` con su lista `issues`
 * (se muestra el `detail` del backend hasta que el frontend tenga su texto).
 */
export function ingestError(error: unknown): IngestErrorResponse | null {
  if (!(error instanceof ApiError) || !isObject(error.body)) return null
  const body = error.body
  if (typeof body.kind !== 'string') return null
  if (!knownIngestKind(body.kind) && !Array.isArray(body.issues)) return null
  return body as unknown as IngestErrorResponse
}

function knownIngestKind(kind: string): kind is IngestErrorKind {
  return Object.hasOwn(INGEST_KIND_TEXT, kind)
}

/** Ficha mínima de un 410 (`GoneResponse`), si lo es. */
export function goneFromError(error: unknown): GoneResponse | null {
  if (!(error instanceof ApiError) || error.status !== 410 || !isObject(error.body)) return null
  const body = error.body
  if (typeof body.uri !== 'string') return null
  return {
    detail: typeof body.detail === 'string' ? body.detail : '',
    uri: body.uri,
    resource: goneResource(body.resource),
    title: typeof body.title === 'string' ? body.title : null,
    withdrawn_at: typeof body.withdrawn_at === 'string' ? body.withdrawn_at : null,
  }
}

function goneResource(value: unknown): GoneResponse['resource'] {
  return value === 'catalog' || value === 'scheme' || value === 'ontology' ? value : 'dataset'
}

const CONFLICT_KINDS: ConflictResponse['kind'][] = ['slug_in_use', 'withdrawn', 'catalog_not_empty', 'in_use']

/** `kind` de un 409 `ConflictResponse` del CRUD, si lo es. */
export function conflictKind(error: unknown): ConflictResponse['kind'] | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !isObject(error.body)) return null
  // `IngestErrorResponse` (409 de `POST /datasets`) también tiene `kind` (`withdrawn`), pero trae `issues`.
  if (Array.isArray(error.body.issues)) return null
  const kind = error.body.kind
  return CONFLICT_KINDS.find((k) => k === kind) ?? null
}

function conflictUris(error: unknown, field: 'datasets' | 'resources'): string[] {
  if (!(error instanceof ApiError) || error.status !== 409 || !isObject(error.body)) return []
  const list = error.body[field]
  return Array.isArray(list) ? list.filter((d): d is string => typeof d === 'string') : []
}

/** URIs de las series de un 409 `ConflictResponse` `catalog_not_empty` (baja de un catálogo con datasets). */
export function conflictDatasets(error: unknown): string[] {
  return conflictUris(error, 'datasets')
}

/** URIs de los esquemas y ontologías de un 409 `catalog_not_empty` (decisión 50). */
export function conflictResources(error: unknown): string[] {
  return conflictUris(error, 'resources')
}

/** Usos de un 409 `ConflictResponse` `in_use` (baja de un esquema o una ontología en uso, decisión 50). */
export function conflictUsedBy(error: unknown): UsageRef[] {
  if (!(error instanceof ApiError) || error.status !== 409 || !isObject(error.body)) return []
  const list = error.body.used_by
  if (!Array.isArray(list)) return []
  return list.filter((u): u is UsageRef => isObject(u) && typeof u.uri === 'string' && typeof u.target === 'string')
}

/** 403 `not_managed` (decisión 50): ontología externa o esquema auxiliar. El 403 por rol no lleva `kind`. */
export function isNotManaged(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && isObject(error.body) && error.body.kind === 'not_managed'
}

/** Qué es `issues[].value` en los `kind` que lo usan. */
const VALUE_LABEL: Partial<Record<string, string>> = {
  prefix_in_use: 'Lo usa',
  deprecated_theme: 'Tema',
  unknown_theme: 'Tema',
}

function issueLines(body: IngestErrorResponse): string[] {
  const lines = (Array.isArray(body.issues) ? body.issues : []).map((issue) => {
    const where = issue.path ?? issue.focus_node
    let line = where ? `${issue.message} (${lastSegment(where)})` : issue.message
    // `issues[].value`: el recurso que ya usa el prefijo (`prefix_in_use`) o el tema afectado
    // (`deprecated_theme`, `unknown_theme`), si el mensaje no lo nombra ya.
    const value = typeof issue.value === 'string' ? issue.value : null
    if (value && VALUE_LABEL[body.kind] && !issue.message.includes(value)) {
      line = `${line} · ${VALUE_LABEL[body.kind]}: ${shortUri(value)}`
    }
    // `deprecated_theme`: los sustitutos del tema retirado, para que el editor sepa por cuál cambiarlo.
    const replacements = Array.isArray(issue.replaced_by) ? issue.replaced_by.filter((r) => typeof r === 'string') : []
    return replacements.length > 0 ? `${line} · Sustitutos: ${replacements.map(lastSegment).join(', ')}` : line
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
  if (conflict === 'in_use') {
    info.message = CRUD_TEXT.inUse
    return info
  }

  const ingest = ingestError(error)
  if (ingest) {
    if (knownIngestKind(ingest.kind)) {
      info.message = context.ingestText?.[ingest.kind] ?? INGEST_KIND_TEXT[ingest.kind]
    } else if (typeof ingest.detail === 'string' && ingest.detail) {
      info.message = ingest.detail
    }
    info.issues = issueLines(ingest)
    if (ingest.kind === 'catalog') info.fields.catalog = INGEST_KIND_TEXT.catalog
    if (ingest.kind === 'withdrawn') info.fields.slug = info.message
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
      info.message = isNotManaged(error) ? CRUD_TEXT.notManaged : CRUD_TEXT.forbidden
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
