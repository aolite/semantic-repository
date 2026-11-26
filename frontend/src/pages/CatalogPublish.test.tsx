import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api'
import { CRUD_TEXT, INGEST_KIND_TEXT } from '../crud/errors'
import { PUBLISH_TEXT } from '../crud/publish'
import { VALIDATION_TEXT } from '../crud/validation'
import { cardFixture, catalogDetailFixture, catalogSummaryFixture, detailFixture, pageFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, lastBody, mockFetch, renderApp, renderLoggedIn } from '../test/utils'
import {
  conceptFixture,
  ontologyFixture,
  ontologyIngestFixture,
  schemeFixture,
  schemeIngestFixture,
  vocabPageFixture,
} from '../test/vocabFixtures'

type Handler = Parameters<typeof mockFetch>[0][string]

function mockCatalog(role?: Role, extra: Record<string, Handler> = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    '/datasets': () => jsonResponse(pageFixture([cardFixture()])),
    '/vocabularies': () => jsonResponse(vocabPageFixture([])),
    '/catalogs': () => jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
    ...extra,
  })
}

async function renderEditor(extra: Record<string, Handler> = {}, role: Role = 'editor') {
  const fetchMock = mockCatalog(role, extra)
  const result = await renderLoggedIn('/')
  await screen.findByRole('link', { name: 'Dataset de prueba' })
  return { fetchMock, ...result }
}

function rdfFile(name = 'esquema.ttl', type = 'text/turtle') {
  return new File(['@prefix skos: <http://www.w3.org/2004/02/skos/core#> .'], name, { type })
}

describe('Catálogo · «Importar SKOS» y «Publicar recurso» (decisión 50)', () => {
  it.each([undefined, 'miembro'] as const)('sin rol de edición (%s) no se ven los botones', async (role) => {
    mockCatalog(role)
    if (role) await renderLoggedIn('/')
    else renderApp('/')
    await screen.findByRole('link', { name: 'Dataset de prueba' })
    expect(screen.queryByRole('button', { name: 'Importar SKOS' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publicar recurso' })).not.toBeInTheDocument()
  })

  it.each(['editor', 'admin'] as const)('%s ve «Importar SKOS» y «Publicar recurso», en ese orden', async (role) => {
    await renderEditor({}, role)
    const group = screen.getByRole('group', { name: 'Publicar' })
    const buttons = within(group).getAllByRole('button')
    expect(buttons.map((b) => b.textContent)).toEqual(['Importar SKOS', 'Publicar recurso'])
    expect(buttons[1]).toHaveAttribute('aria-haspopup', 'menu')
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'false')
  })

  it('el menú lista nuevo catálogo, dataset, vocabulario y ontología, y se maneja con el teclado', async () => {
    const { user } = await renderEditor()
    const button = screen.getByRole('button', { name: 'Publicar recurso' })
    await user.click(button)
    const menu = screen.getByRole('menu', { name: 'Publicar recurso' })
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const items = within(menu).getAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Nuevo catálogo', 'Nuevo dataset', 'Nuevo vocabulario', 'Nueva ontología'])
    expect(items[0]).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(items[1]).toHaveFocus()
    await user.keyboard('{End}')
    expect(items[3]).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(items[0]).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
    // Con la flecha arriba se abre en la última opción.
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'Nueva ontología' })).toHaveFocus()
  })

  it('«Nuevo catálogo» usa el formulario de la decisión 49 y va a la ficha del catálogo', async () => {
    const { user, fetchMock } = await renderEditor({
      '/catalogs': (_u, init) =>
        init?.method === 'POST'
          ? jsonResponse(catalogDetailFixture({ slug: 'nuevo', title: 'Nuevo' }), 201)
          : jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
      '/catalogs/nuevo': () => jsonResponse(catalogDetailFixture({ slug: 'nuevo', title: 'Nuevo' })),
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nuevo catálogo' }))
    expect(screen.getByRole('heading', { name: 'Nuevo catálogo' })).toBeInTheDocument()
    expect(screen.getByLabelText('Slug')).toHaveFocus()
    await user.type(screen.getByLabelText('Slug'), 'nuevo')
    await user.type(screen.getByLabelText('Título (en español)'), 'Nuevo')
    await user.type(screen.getByLabelText('Descripción (en español)'), 'Descripción')
    await user.type(screen.getByLabelText('Publicador'), 'Unidad')
    await user.click(screen.getByRole('button', { name: 'Crear catálogo' }))
    expect(await screen.findByText('Catálogo creado.')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'POST', '/catalogs')).toEqual({
      slug: 'nuevo',
      title: 'Nuevo',
      description: 'Descripción',
      publisher_name: 'Unidad',
    })
  })

  it('«Nuevo dataset» obliga a elegir catálogo y crea la serie en él', async () => {
    const created = detailFixture({ slug: 'nuevo', title: 'Nuevo', version: null, versions: [], current_version: null })
    const { user, fetchMock } = await renderEditor({
      '/catalogs/catalogo-prueba/datasets': () => jsonResponse(created, 201),
      '/datasets/nuevo': () => jsonResponse(created),
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nuevo dataset' }))
    const form = screen.getByRole('region', { name: 'Nuevo dataset' })
    await user.type(within(form).getByLabelText('Slug'), 'nuevo')
    await user.type(within(form).getByLabelText('Título (en español)'), 'Nuevo')
    await user.type(within(form).getByLabelText('Descripción (en español)'), 'Descripción')
    await user.click(within(form).getByRole('button', { name: 'Crear dataset' }))
    const select = within(form).getByLabelText('Catálogo')
    expect(select).toHaveAttribute('aria-invalid', 'true')
    expect(select).toHaveFocus()
    expect(callsTo(fetchMock, 'POST', '/catalogs/catalogo-prueba/datasets')).toHaveLength(0)

    await user.selectOptions(select, 'catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Crear dataset' }))
    expect(await screen.findByText('Dataset creado. Publica su primera versión con «Nueva versión».')).toBeInTheDocument()
    expect(lastBody(fetchMock, 'POST', '/catalogs/catalogo-prueba/datasets')).toEqual({
      slug: 'nuevo',
      title: 'Nuevo',
      description: 'Descripción',
      publisher_name: null,
    })
  })

  it('«Importar SKOS» valida fichero y catálogo, publica con ?catalog= y va al Navegador SKOS', async () => {
    const { user, fetchMock } = await renderEditor({
      '/schemes': () => jsonResponse(schemeIngestFixture(), 201),
      '/schemes/esq-prueba': () => jsonResponse(schemeFixture()),
      '/schemes/esq-prueba/concepts/grupo-a': () => jsonResponse(conceptFixture({ slug: 'grupo-a', pref_label: 'Grupo A' })),
    })
    const importButton = screen.getByRole('button', { name: 'Importar SKOS' })
    await user.click(importButton)
    expect(importButton).toHaveAttribute('aria-expanded', 'true')
    const form = screen.getByRole('region', { name: 'Importar SKOS' })
    const fileInput = within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)')
    expect(fileInput).toHaveFocus()

    await user.click(within(form).getByRole('button', { name: 'Publicar esquema' }))
    expect(within(form).getByRole('alert')).toHaveTextContent(VALIDATION_TEXT.file)
    expect(fileInput).toHaveAttribute('aria-invalid', 'true')

    await user.upload(fileInput, rdfFile())
    await user.click(within(form).getByRole('button', { name: 'Publicar esquema' }))
    expect(within(form).getByRole('alert')).toHaveTextContent(PUBLISH_TEXT.catalogRequired)
    expect(within(form).getByLabelText('Catálogo')).toHaveFocus()
    expect(callsTo(fetchMock, 'POST', '/schemes')).toHaveLength(0)

    await user.selectOptions(within(form).getByLabelText('Catálogo'), 'catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Publicar esquema' }))
    expect(await screen.findByText('Esquema publicado con 6 conceptos.')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Esquema de dominio de prueba' })).toBeInTheDocument()
    const [call] = callsTo(fetchMock, 'POST', '/schemes')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(call[1]?.headers).toMatchObject({ 'Content-Type': 'text/turtle', Authorization: 'Bearer token-de-prueba' })
    expect(call[1]?.body).toBeInstanceOf(File)
  })

  it('«Nuevo vocabulario» abre el mismo formulario con otro título; Cancelar devuelve el foco al menú', async () => {
    const { user } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nuevo vocabulario' }))
    const form = screen.getByRole('region', { name: 'Nuevo vocabulario' })
    await user.click(within(form).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('region', { name: 'Nuevo vocabulario' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publicar recurso' })).toHaveFocus()
  })

  it.each([
    [
      'concepts_removed (409)',
      409,
      {
        detail: 'x',
        kind: 'concepts_removed',
        issues: [{ message: 'Falta el concepto', focus_node: 'http://uri.test/itot/vocab/esq-prueba/viejo', path: null, value: null, severity: 'Violation', source_shape: null }],
        report: null,
      },
      INGEST_KIND_TEXT.concepts_removed,
      'Falta el concepto (viejo)',
    ],
    ['prefix_withdrawn (409)', 409, { detail: 'x', kind: 'prefix_withdrawn', issues: [], report: null }, INGEST_KIND_TEXT.prefix_withdrawn, null],
    ['concept_reactivated (409)', 409, { detail: 'x', kind: 'concept_reactivated', issues: [], report: null }, INGEST_KIND_TEXT.concept_reactivated, null],
    ['replacement (422)', 422, { detail: 'x', kind: 'replacement', issues: [], report: null }, INGEST_KIND_TEXT.replacement, null],
    ['shacl (422)', 422, { detail: 'x', kind: 'shacl', issues: [{ message: 'Valor obligatorio', focus_node: null, path: 'http://purl.org/dc/terms/title', value: null, severity: 'Violation', source_shape: null }], report: 'x' }, INGEST_KIND_TEXT.shacl, 'Valor obligatorio (title)'],
    ['catalog_conflict (409)', 409, { detail: 'x', kind: 'catalog_conflict', issues: [], report: null }, 'El esquema ya está en otro catálogo', null],
    ['not_managed (403)', 403, { detail: 'x', kind: 'not_managed' }, CRUD_TEXT.notManaged, null],
    ['403 por rol', 403, { detail: 'x' }, CRUD_TEXT.forbidden, null],
  ])('error %s: lo muestra en el formulario', async (_name, status, body, message, issue) => {
    const { user } = await renderEditor({ '/schemes': () => jsonResponse(body, status) })
    await user.click(screen.getByRole('button', { name: 'Importar SKOS' }))
    const form = screen.getByRole('region', { name: 'Importar SKOS' })
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), rdfFile())
    await user.selectOptions(within(form).getByLabelText('Catálogo'), 'catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Publicar esquema' }))
    const alert = await within(form).findByRole('alert')
    expect(alert).toHaveTextContent(message)
    if (issue) expect(within(alert).getByText(issue)).toBeInTheDocument()
  })

  it('503 con Retry-After: el servidor está ocupado', async () => {
    const { user } = await renderEditor({
      '/ontologies': () =>
        new Response(JSON.stringify({ detail: 'Bloqueo' }), { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': '5' } }),
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nueva ontología' }))
    const form = screen.getByRole('region', { name: 'Nueva ontología' })
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), rdfFile('onto.jsonld', 'application/ld+json'))
    await user.selectOptions(within(form).getByLabelText('Catálogo'), 'catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Publicar ontología' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(CRUD_TEXT.busy)
  })

  it('«Nueva ontología» publica la versión en el catálogo y va a su ficha', async () => {
    const { user, fetchMock } = await renderEditor({
      '/ontologies': () => jsonResponse(ontologyIngestFixture(), 201),
      '/ontologies/onto-prueba': () => jsonResponse(ontologyFixture()),
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nueva ontología' }))
    const form = screen.getByRole('region', { name: 'Nueva ontología' })
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), rdfFile('onto.jsonld', 'application/ld+json'))
    await user.selectOptions(within(form).getByLabelText('Catálogo'), 'catalogo-prueba')
    await user.click(within(form).getByRole('button', { name: 'Publicar ontología' }))
    expect(await screen.findByText('Versión 1.3.0 de la ontología publicada.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Ontología de prueba'))
    const [call] = callsTo(fetchMock, 'POST', '/ontologies')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
    expect(call[1]?.headers).toMatchObject({ 'Content-Type': 'application/ld+json' })
  })
})
