import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import { goneFixture } from '../test/fixtures'
import { conflictDatasets, conflictKind, CRUD_TEXT, describeError, goneFromError, INGEST_KIND_TEXT, ingestError } from './errors'

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

  it('ingestError ignora kinds desconocidos', () => {
    expect(ingestError(apiError(422, ingest('otro')))).toBeNull()
    expect(ingestError(apiError(422, ingest('shacl')))?.kind).toBe('shacl')
  })
})
