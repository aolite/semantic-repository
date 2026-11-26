import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api'
import { PUBLISH_OPTIONS, publishOptions } from '../crud/publish'
import { cardFixture, catalogDetailFixture, catalogSummaryFixture, goneFixture, pageFixture } from '../test/fixtures'
import { authRoutes, callsTo, jsonResponse, mockFetch, renderLoggedIn } from '../test/utils'
import { ontologyFixture, ontologyIngestFixture, schemeFixture, schemeIngestFixture, conceptFixture } from '../test/vocabFixtures'

const PATH = '/catalogs/catalogo-prueba'
const ROUTE = '/catalogos/catalogo-prueba'

type Handler = Parameters<typeof mockFetch>[0][string]

async function renderEditor(extra: Record<string, Handler> = {}, role: Role = 'editor') {
  const fetchMock = mockFetch({
    ...authRoutes(role),
    [PATH]: () => jsonResponse(catalogDetailFixture()),
    '/datasets': () => jsonResponse(pageFixture([cardFixture()], { page_size: 20 })),
    '/catalogs': () => jsonResponse({ items: [catalogSummaryFixture()], total: 1 }),
    ...extra,
  })
  const result = await renderLoggedIn(ROUTE)
  await screen.findByRole('heading', { level: 1, name: 'Catálogo de prueba' })
  return { fetchMock, ...result }
}

function rdfFile(name = 'esquema.ttl', type = 'text/turtle') {
  return new File(['@prefix skos: <http://www.w3.org/2004/02/skos/core#> .'], name, { type })
}

describe('publishOptions', () => {
  it('sin catálogo fijo, las cuatro opciones; con catálogo fijo, sin «Nuevo catálogo»', () => {
    expect(publishOptions(false)).toEqual(PUBLISH_OPTIONS)
    expect(publishOptions(true).map((o) => o.label)).toEqual(['Nuevo dataset', 'Nuevo vocabulario', 'Nueva ontología'])
  })
})

describe('Ficha de catálogo · publicar en el catálogo (decisión 50)', () => {
  it.each(['editor', 'admin'] as const)(
    '%s ve «Importar SKOS» y «Publicar recurso» con el estilo de la pantalla Catálogo',
    async (role) => {
      await renderEditor({}, role)
      const group = screen.getByRole('group', { name: 'Publicar' })
      const buttons = within(group).getAllByRole('button')
      expect(buttons.map((b) => b.textContent)).toEqual(['Importar SKOS', 'Publicar recurso'])
      expect(buttons[0]).toHaveClass('button--outline', 'catalog__action')
      expect(buttons[1]).toHaveClass('button--primary', 'catalog__action', 'catalog__action--primary')
      // «Nuevo dataset» ya no es un botón suelto: está en el menú.
      expect(screen.queryByRole('button', { name: 'Nuevo dataset' })).not.toBeInTheDocument()
    },
  )

  it('el menú no ofrece «Nuevo catálogo» y se maneja con el teclado', async () => {
    const { user } = await renderEditor()
    const button = screen.getByRole('button', { name: 'Publicar recurso' })
    button.focus()
    await user.keyboard('{ArrowDown}')
    const items = within(screen.getByRole('menu', { name: 'Publicar recurso' })).getAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Nuevo dataset', 'Nuevo vocabulario', 'Nueva ontología'])
    expect(items[0]).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
  })

  it('un catálogo dado de baja (410) no muestra los botones', async () => {
    mockFetch({
      ...authRoutes('editor'),
      [PATH]: () => jsonResponse(goneFixture({ resource: 'catalog', title: 'Catálogo retirado' }), 410),
    })
    await renderLoggedIn(ROUTE)
    await screen.findByRole('heading', { level: 1, name: 'Catálogo retirado' })
    expect(screen.queryByRole('button', { name: 'Importar SKOS' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Publicar recurso' })).not.toBeInTheDocument()
  })

  it('«Importar SKOS» muestra el catálogo de destino, sin selector, y publica con ?catalog=', async () => {
    const { user, fetchMock } = await renderEditor({
      '/schemes': () => jsonResponse(schemeIngestFixture(), 201),
      '/schemes/esq-prueba': () => jsonResponse(schemeFixture()),
      '/schemes/esq-prueba/concepts/grupo-a': () => jsonResponse(conceptFixture({ slug: 'grupo-a', pref_label: 'Grupo A' })),
    })
    const importButton = screen.getByRole('button', { name: 'Importar SKOS' })
    await user.click(importButton)
    expect(importButton).toHaveAttribute('aria-expanded', 'true')
    const form = screen.getByRole('region', { name: 'Importar SKOS en este catálogo' })
    expect(form).toHaveTextContent('Catálogo: Catálogo de prueba')
    expect(within(form).queryByLabelText('Catálogo')).not.toBeInTheDocument()
    const fileInput = within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)')
    expect(fileInput).toHaveFocus()
    await user.upload(fileInput, rdfFile())
    await user.click(within(form).getByRole('button', { name: 'Publicar esquema' }))

    expect(await screen.findByText('Esquema publicado con 6 conceptos.')).toBeInTheDocument()
    const [call] = callsTo(fetchMock, 'POST', '/schemes')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
  })

  it('«Nuevo vocabulario»: título propio; Cancelar devuelve el foco a «Publicar recurso»', async () => {
    const { user } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nuevo vocabulario' }))
    const form = screen.getByRole('region', { name: 'Nuevo vocabulario en este catálogo' })
    expect(form).toHaveTextContent('Catálogo: Catálogo de prueba')
    await user.click(within(form).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('region', { name: 'Nuevo vocabulario en este catálogo' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publicar recurso' })).toHaveFocus()
  })

  it('«Nueva ontología» publica la versión con ?catalog= y va a su ficha', async () => {
    const { user, fetchMock } = await renderEditor({
      '/ontologies': () => jsonResponse(ontologyIngestFixture(), 201),
      '/ontologies/onto-prueba': () => jsonResponse(ontologyFixture()),
    })
    await user.click(screen.getByRole('button', { name: 'Publicar recurso' }))
    await user.click(screen.getByRole('menuitem', { name: 'Nueva ontología' }))
    const form = screen.getByRole('region', { name: 'Nueva ontología en este catálogo' })
    expect(within(form).queryByLabelText('Catálogo')).not.toBeInTheDocument()
    await user.upload(within(form).getByLabelText('Fichero RDF (Turtle o JSON-LD)'), rdfFile('onto.jsonld', 'application/ld+json'))
    await user.click(within(form).getByRole('button', { name: 'Publicar ontología' }))
    expect(await screen.findByText('Versión 1.3.0 de la ontología publicada.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Ontología de prueba'))
    const [call] = callsTo(fetchMock, 'POST', '/ontologies')
    expect(new URL(String(call[0])).searchParams.get('catalog')).toBe('catalogo-prueba')
  })

  it('abrir un formulario de publicar cierra «Editar catálogo», y al revés', async () => {
    const { user } = await renderEditor()
    await user.click(screen.getByRole('button', { name: 'Editar catálogo' }))
    expect(screen.getByRole('region', { name: 'Editar catálogo' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Importar SKOS' }))
    expect(screen.queryByRole('region', { name: 'Editar catálogo' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Importar SKOS en este catálogo' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Editar catálogo' }))
    expect(screen.queryByRole('region', { name: 'Importar SKOS en este catálogo' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Editar catálogo' })).toBeInTheDocument()
  })

  it('las tarjetas de dataset no dicen «Catálogo: …» (se llega por la miga de pan)', async () => {
    await renderEditor()
    const list = await screen.findByRole('list', { name: 'Datasets del catálogo' })
    expect(within(list).queryByText(/Catálogo:/)).not.toBeInTheDocument()
  })
})
