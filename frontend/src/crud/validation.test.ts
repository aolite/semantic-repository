import { describe, expect, it } from 'vitest'
import { mediaTypeForFile, validateResource, VALIDATION_TEXT } from './validation'

const VALID = { slug: 'catalogo-a1', title: 'Título', description: 'Descripción', publisher_name: 'Publicador' }

describe('Validación de los formularios', () => {
  it('acepta un formulario completo', () => {
    expect(validateResource(VALID, { requireSlug: true, requirePublisher: true })).toEqual({})
  })

  it.each(['', 'Mayus', 'con espacio', '-guion', 'guion-', 'doble--guion', 'acentuado-á', 'a'.repeat(201)])(
    'rechaza el slug «%s»',
    (slug) => {
      const errors = validateResource({ ...VALID, slug }, { requireSlug: true, requirePublisher: true })
      expect(errors.slug).toBe(slug ? VALIDATION_TEXT.slug : VALIDATION_TEXT.required)
    },
  )

  it('no valida el slug al editar', () => {
    expect(validateResource({ ...VALID, slug: '' }, { requireSlug: false, requirePublisher: true })).toEqual({})
  })

  it('exige título, descripción y, en catálogos, publicador', () => {
    const empty = { slug: 'a', title: ' ', description: '', publisher_name: '' }
    expect(validateResource(empty, { requireSlug: true, requirePublisher: true })).toEqual({
      title: VALIDATION_TEXT.required,
      description: VALIDATION_TEXT.required,
      publisher_name: VALIDATION_TEXT.required,
    })
    expect(validateResource(empty, { requireSlug: true, requirePublisher: false }).publisher_name).toBeUndefined()
  })

  it('deduce el tipo de medio por la extensión', () => {
    expect(mediaTypeForFile('serie.TTL')).toBe('text/turtle')
    expect(mediaTypeForFile('serie.jsonld')).toBe('application/ld+json')
    expect(mediaTypeForFile('serie.json')).toBe('application/ld+json')
    expect(mediaTypeForFile('serie.rdf')).toBeNull()
  })
})
