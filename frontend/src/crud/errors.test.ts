import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import { goneFixture } from '../test/fixtures'
import {
  conflictDatasets,
  conflictKind,
  conflictResources,
  conflictUsedBy,
  CRUD_TEXT,
  describeError,
  goneFromError,
  INGEST_KIND_TEXT,
  ingestError,
  isNotManaged,
  SCHEME_INGEST_TEXT,
} from './errors'

const CONTEXT = { notFound: 'No existe de prueba.', fallback: 'Fallo de prueba.' }

function apiError(status: number, body: unknown = null) {
  const detail = body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string' ? body.detail : null
  return new ApiError(status, 'x', detail, null, body)
}

function ingest(kind: string, extra: object = {}) {
  return { detail: 'detalle de prueba', kind, issues: [], report: null, ...extra }
}

describe('Errores de los formularios de catálogos y datasets', () => {
  it.each([
    ['slug_in_use', CRUD_TEXT.slugInUse],
    ['withdrawn', CRUD_TEXT.slugWithdrawn],
  ] as const)('409 ConflictResponse %s: mensaje propio en el slug', (kind, text) => {
    const info = describeError(apiError(409, { detail: 'x', kind }), CONTEXT)
    expect(info.message).toBe(text)
    expect(info.fields.slug).toBe(text)
  })

  it('409 ConflictResponse catalog_not_empty: el catálogo tiene datasets', () => {
    const body = { detail: 'x', kind: 'catalog_not_empty', datasets: ['http://uri.test/itot/dataset/a'] }
    expect(describeError(apiError(409, body), CONTEXT).message).toBe(CRUD_TEXT.catalogHasDatasets)
    expect(conflictKind(apiError(409, body))).toBe('catalog_not_empty')
    expect(conflictKind(apiError(422, body))).toBeNull()
  })

  it('409 sin kind (respuesta antigua) marca el slug con el texto genérico', () => {
    const info = describeError(apiError(409, { detail: 'Ya existe un catálogo con ese slug' }), CONTEXT)
    expect(info.message).toBe(CRUD_TEXT.slugTaken)
    expect(info.fields.slug).toBe(CRUD_TEXT.slugTaken)
  })

  it.each([
    ['withdrawn', 409],
    ['catalog_conflict', 409],
    ['version_removed', 409],
    ['version_immutable', 409],
    ['catalog', 422],
    ['shacl', 422],
    ['syntax', 422],
    ['limit', 422],
  ] as const)('%s (%i) usa el texto de su kind', (kind, status) => {
    expect(describeError(apiError(status, ingest(kind)), CONTEXT).message).toBe(INGEST_KIND_TEXT[kind])
  })

  it('withdrawn marca el slug y catalog marca el catálogo', () => {
    expect(describeError(apiError(409, ingest('withdrawn')), CONTEXT).fields.slug).toBeTruthy()
    expect(describeError(apiError(422, ingest('catalog')), CONTEXT).fields.catalog).toBeTruthy()
  })

  it('lista las incidencias SHACL o las versiones afectadas, con su ruta', () => {
    const body = ingest('version_removed', {
      issues: [
        { message: 'Falta la versión', focus_node: 'http://uri.test/itot/dataset/d/1.0.0', path: null, value: null, severity: 'Violation', source_shape: null },
        { message: 'Valor obligatorio', focus_node: null, path: 'http://purl.org/dc/terms/title', value: null, severity: 'Violation', source_shape: null },
      ],
    })
    expect(describeError(apiError(409, body), CONTEXT).issues).toEqual(['Falta la versión (1.0.0)', 'Valor obligatorio (title)'])
  })

  it('422 de validación marca los campos por su loc, sin mostrar valores', () => {
    const body = { detail: [{ loc: ['body', 'slug'], msg: 'String should match pattern', type: 'string_pattern_mismatch' }, { loc: ['body', 'extra'], msg: 'x', type: 'extra_forbidden' }] }
    const info = describeError(apiError(422, body), CONTEXT)
    expect(info.message).toBe(CRUD_TEXT.invalidFields)
    expect(info.fields).toEqual({ slug: CRUD_TEXT.invalidField })
  })

  it.each([
    [0, CRUD_TEXT.offline],
    [401, CRUD_TEXT.unauthorized],
    [403, CRUD_TEXT.forbidden],
    [404, 'No existe de prueba.'],
    [413, CRUD_TEXT.tooLarge],
    [415, CRUD_TEXT.unsupported],
    [503, CRUD_TEXT.unavailable],
    [500, 'Fallo de prueba.'],
  ])('%i → %s', (status, text) => {
    expect(describeError(apiError(status), CONTEXT).message).toBe(text)
  })

  it('503 con Retry-After (bloqueo de escritura): el servidor está ocupado', () => {
    const busy = new ApiError(503, 'x', 'Bloqueo ocupado', 5, { detail: 'Bloqueo ocupado' })
    expect(describeError(busy, CONTEXT).message).toBe('El servidor está ocupado; inténtalo de nuevo en unos segundos.')
    expect(describeError(apiError(503), CONTEXT).message).toBe(CRUD_TEXT.unavailable)
  })

  it('410 nombra el recurso dado de baja', () => {
    expect(describeError(apiError(410, goneFixture({ title: 'Recurso X' })), CONTEXT).message).toBe('«Recurso X» se dio de baja.')
    expect(describeError(apiError(410, goneFixture({ title: null })), CONTEXT).message).toBe(CRUD_TEXT.gone)
  })

  it('un error que no es de la API da el texto genérico', () => {
    expect(describeError(new Error('x'), CONTEXT).message).toBe('Fallo de prueba.')
  })

  it('goneFromError solo reconoce 410 con GoneResponse', () => {
    expect(goneFromError(apiError(410, goneFixture()))).toEqual(goneFixture())
    expect(goneFromError(apiError(410, { detail: 'x' }))).toBeNull()
    expect(goneFromError(apiError(404, goneFixture()))).toBeNull()
    expect(goneFromError(new Error('x'))).toBeNull()
  })

  it('conflictDatasets devuelve las URIs del 409 de baja de un catálogo', () => {
    expect(conflictDatasets(apiError(409, { detail: 'x', kind: 'catalog_not_empty', datasets: ['http://uri.test/itot/dataset/a'] }))).toEqual([
      'http://uri.test/itot/dataset/a',
    ])
    expect(conflictDatasets(apiError(409, { detail: 'x' }))).toEqual([])
    expect(conflictDatasets(apiError(422, { datasets: ['a'] }))).toEqual([])
  })

  it('ingestError reconoce un kind nuevo del backend si trae issues, y muestra su detail', () => {
    expect(ingestError(apiError(422, { detail: 'x', kind: 'otro' }))).toBeNull()
    expect(ingestError(apiError(422, ingest('shacl')))?.kind).toBe('shacl')
    const body = ingest('otro', {
      detail: 'Detalle nuevo del backend.',
      issues: [{ message: 'Incidencia', focus_node: null, path: null, value: null, severity: 'Violation', source_shape: null }],
    })
    expect(ingestError(apiError(422, body))?.kind).toBe('otro')
    const info = describeError(apiError(422, body), CONTEXT)
    expect(info.message).toBe('Detalle nuevo del backend.')
    expect(info.issues).toEqual(['Incidencia'])
  })

  it.each([
    ['prefix_withdrawn', 409],
    ['concepts_removed', 409],
    ['concept_reactivated', 409],
    ['replacement', 422],
    ['deprecated_theme', 422],
    ['prefix_in_use', 409],
    ['unknown_theme', 422],
  ] as const)('decisión 50: %s (%i) usa el texto de su kind', (kind, status) => {
    expect(describeError(apiError(status, ingest(kind)), CONTEXT).message).toBe(INGEST_KIND_TEXT[kind])
  })

  it('ingestText sustituye el texto de un kind para el recurso (catalog_conflict de un esquema)', () => {
    const info = describeError(apiError(409, ingest('catalog_conflict')), { ...CONTEXT, ingestText: SCHEME_INGEST_TEXT })
    expect(info.message).toBe(SCHEME_INGEST_TEXT.catalog_conflict)
    expect(describeError(apiError(409, ingest('withdrawn')), { ...CONTEXT, ingestText: SCHEME_INGEST_TEXT }).fields.slug).toBe(
      SCHEME_INGEST_TEXT.withdrawn,
    )
  })

  it('deprecated_theme lista cada tema retirado con sus sustitutos', () => {
    const body = ingest('deprecated_theme', {
      issues: [
        {
          message: 'Tema retirado',
          focus_node: 'http://uri.test/itot/dataset/d/2.0.0',
          path: null,
          value: 'http://uri.test/itot/vocab/ot/viejo',
          severity: 'Violation',
          source_shape: null,
          replaced_by: ['http://uri.test/itot/vocab/ot/nuevo-a', 'http://uri.test/itot/vocab/ot/nuevo-b'],
        },
        { message: 'Tema retirado sin sustitutos', focus_node: null, path: null, value: null, severity: 'Violation', source_shape: null, replaced_by: [] },
      ],
    })
    expect(describeError(apiError(422, body), CONTEXT).issues).toEqual([
      'Tema retirado (2.0.0) · Tema: vocab/ot/viejo · Sustitutos: nuevo-a, nuevo-b',
      'Tema retirado sin sustitutos',
    ])
  })

  it('prefix_in_use nombra el recurso que ya usa el prefijo (issues[].value)', () => {
    const body = ingest('prefix_in_use', {
      issues: [{ message: 'Prefijo en uso', focus_node: null, path: null, value: 'http://uri.test/itot/vocab/otro', severity: 'Violation', source_shape: null }],
    })
    expect(describeError(apiError(409, body), CONTEXT).issues).toEqual(['Prefijo en uso · Lo usa: vocab/otro'])
  })

  it('unknown_theme lista los temas que no son conceptos vivos, sin repetir el que ya nombra el mensaje', () => {
    const body = ingest('unknown_theme', {
      issues: [
        { message: 'Tema desconocido', focus_node: 'http://uri.test/itot/dataset/d/2.0.0', path: null, value: 'http://uri.test/itot/vocab/baja/c', severity: 'Violation', source_shape: null, replaced_by: [] },
        { message: 'Tema http://uri.test/itot/vocab/x/y desconocido', focus_node: null, path: null, value: 'http://uri.test/itot/vocab/x/y', severity: 'Violation', source_shape: null },
      ],
    })
    expect(describeError(apiError(422, body), CONTEXT).issues).toEqual([
      'Tema desconocido (2.0.0) · Tema: vocab/baja/c',
      'Tema http://uri.test/itot/vocab/x/y desconocido',
    ])
  })

  it('409 ConflictResponse in_use: el esquema o la ontología están en uso, con used_by', () => {
    const usage = { uri: 'http://uri.test/itot/dataset/d/1.0.0', resource: 'dataset', via: 'dcat:theme', target: 'http://uri.test/itot/vocab/ot/a' }
    const error = apiError(409, { detail: 'x', kind: 'in_use', used_by: [usage, { uri: 1 }] })
    expect(conflictKind(error)).toBe('in_use')
    expect(describeError(error, CONTEXT).message).toBe(CRUD_TEXT.inUse)
    expect(conflictUsedBy(error)).toEqual([usage])
    expect(conflictUsedBy(apiError(409, { detail: 'x', kind: 'in_use' }))).toEqual([])
  })

  it('conflictResources devuelve los esquemas y ontologías del 409 catalog_not_empty', () => {
    const body = { detail: 'x', kind: 'catalog_not_empty', datasets: [], resources: ['http://uri.test/itot/vocab/ot', 7] }
    expect(conflictResources(apiError(409, body))).toEqual(['http://uri.test/itot/vocab/ot'])
    expect(conflictResources(apiError(422, body))).toEqual([])
  })

  it('403 not_managed (recurso no gestionable) es distinto del 403 por rol, que no lleva kind', () => {
    const notManaged = apiError(403, { detail: 'x', kind: 'not_managed' })
    expect(isNotManaged(notManaged)).toBe(true)
    expect(describeError(notManaged, CONTEXT).message).toBe(CRUD_TEXT.notManaged)
    expect(isNotManaged(apiError(403, { detail: 'x' }))).toBe(false)
    expect(describeError(apiError(403, { detail: 'x', kind: null }), CONTEXT).message).toBe(CRUD_TEXT.forbidden)
  })

  it('goneFromError reconoce las bajas de esquemas y ontologías', () => {
    expect(goneFromError(apiError(410, goneFixture({ resource: 'scheme' })))?.resource).toBe('scheme')
    expect(goneFromError(apiError(410, goneFixture({ resource: 'ontology' })))?.resource).toBe('ontology')
  })
})
