import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api'
import { INGEST_KIND_TEXT } from '../crud/errors'
import { authRoutes, callsTo, jsonResponse, mockFetch, renderApp, renderLoggedIn } from '../test/utils'
import { externalOntologyFixture, externalReplaceFixture, externalVersionFixture } from '../test/vocabFixtures'

const PATH = '/ontologies/externas/ext'
const POST = '/ontologies/externas/ext/versions'
const ROUTE = '/ontologias/externas/ext'
const TITLE = 'Ontología externa de prueba'

type Handler = Parameters<typeof mockFetch>[0][string]

function mockExternal({ role, detail, replace }: { role?: Role; detail?: Handler; replace?: Handler } = {}) {
  return mockFetch({
    ...(role ? authRoutes(role) : {}),
    [PATH]: detail ?? (() => jsonResponse(externalOntologyFixture())),
    ...(replace ? { [POST]: replace } : {}),
  })
}

function ingestBody(kind: string, issues: object[] = []) {
  return { detail: 'detalle de prueba', kind, issues, report: null }
}

async function openDialog(options: Parameters<typeof mockExternal>[0] = {}) {
  const fetchMock = mockExternal({ role: 'editor', ...options })
  const result = await renderLoggedIn(ROUTE)
  await screen.findByRole('heading', { level: 1, name: TITLE })
  await result.user.click(screen.getByRole('button', { name: 'Sustituir ontología' }))
  const dialog = screen.getByRole('dialog', { name: 'Sustituir ontología' })
  return { fetchMock, dialog, ...result }
}

describe('Ficha de ontología externa (decisión 51)', () => {
  it('cabecera: migas, owl:Ontology, «Ontología externa», «Referenciada», versión actual, IRI oficial y descargas', async () => {
    mockExternal()
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: TITLE })).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Migas de pan' })
    expect(within(crumbs).getByRole('link', { name: 'Vocabularios' })).toHaveAttribute('href', '/vocabularios')
    expect(within(crumbs).getByText('Ontologías externas')).toBeInTheDocument()
    expect(within(crumbs).getByText('ext')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('owl:Ontology')).toBeInTheDocument()
    expect(screen.getByText('Ontología externa', { selector: '.tag' })).toBeInTheDocument()
    expect(screen.getByText('Referenciada', { selector: '.tag' })).toBeInTheDocument()
    expect(screen.getByText('v2.0-prueba · actual')).toBeInTheDocument()
    expect(document.querySelector('.vocab-header__ns')).toHaveTextContent('ext: https://externa.test/onto#')
    expect(screen.getByText('https://externa.test/onto/', { selector: '.dataset__uri' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Copiar URI/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Descargar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/externas/ext/rdf?format=turtle&download=1',
    )
    // Solo lectura: ni editar, ni dar de baja, ni sustituir sin sesión.
    expect(screen.queryByRole('button', { name: 'Sustituir ontología' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dar de baja' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Editar/ })).not.toBeInTheDocument()
  })

  it('métricas de la versión actual y versionado con número, fecha, nota, estado y descarga', async () => {
    mockExternal()
    renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: TITLE })
    expect(screen.getByText('calculadas en backend · versión 2')).toBeInTheDocument()
    const metrics = screen.getByRole('list', { name: 'Métricas OWL' })
    expect(within(metrics).getByText('13')).toBeInTheDocument()

    const versioning = screen.getByRole('region', { name: 'Versionado' })
    const rows = within(versioning).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByRole('link', { name: 'Versión 2' })).toHaveTextContent('2 · 2.0-prueba')
    expect(within(rows[0]).getByRole('link', { name: 'Versión 2' })).toHaveAttribute('aria-current', 'page')
    expect(within(rows[0]).getByRole('link', { name: 'Versión 2' })).toHaveAttribute('href', ROUTE)
    expect(within(rows[0]).getByText('Actual')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Notas de prueba de la 2.')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/20 feb 2000/)).toBeInTheDocument()
    expect(within(rows[1]).getByRole('link', { name: 'Versión 1' })).toHaveAttribute('href', `${ROUTE}?version=1`)
    expect(within(rows[1]).getByText('Sustituida')).toBeInTheDocument()
    expect(within(rows[1]).getByRole('link', { name: 'Descargar el RDF de la versión 1 (Turtle)' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/externas/ext/rdf?format=turtle&version=1&download=1',
    )
  })

  it('?version=1 resalta esa versión y muestra sus métricas y descargas', async () => {
    mockExternal()
    renderApp(`${ROUTE}?version=1`)
    await screen.findByRole('heading', { level: 1, name: TITLE })
    expect(screen.getByText('calculadas en backend · versión 1')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Métricas OWL' })).getByText('3')).toBeInTheDocument()
    expect(screen.getByText('Versión 1', { selector: '.tag' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Versión 1' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Versión 2' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Descargar Turtle' })).toHaveAttribute(
      'href',
      'http://api.test/ontologies/externas/ext/rdf?format=turtle&version=1&download=1',
    )
  })

  it('una versión que no existe y una externa que no existe', async () => {
    mockExternal()
    const { unmount } = renderApp(`${ROUTE}?version=9`)
    expect(await screen.findByRole('heading', { level: 1, name: 'Versión no encontrada' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver la ficha de la ontología' })).toHaveAttribute('href', ROUTE)
    unmount()
    mockExternal({ detail: () => jsonResponse({ detail: 'Not Found' }, 404) })
    renderApp(ROUTE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Ontología no encontrada' })).toBeInTheDocument()
  })

  it('sin versiones: solo «Referenciada», sin descarga y con estados vacíos', async () => {
    mockExternal({ detail: () => jsonResponse(externalOntologyFixture({ current_version: null, versions: [], version: null })) })
    renderApp(ROUTE)
    await screen.findByRole('heading', { level: 1, name: TITLE })
    expect(screen.getByText('Referenciada', { selector: '.tag' })).toBeInTheDocument()
    expect(screen.queryByText(/· actual/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Descargar Turtle' })).not.toBeInTheDocument()
    expect(screen.getByText(/todavía no se ha sustituido nunca/)).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Métricas OWL' })).not.toBeInTheDocument()
    expect(screen.getByText(/Todavía no tiene versiones/)).toBeInTheDocument()
  })

  it('el miembro no ve «Sustituir ontología»; el editor y el admin, sí', async () => {
    mockExternal({ role: 'miembro' })
    const { unmount } = await renderLoggedIn(ROUTE)
    await screen.findByRole('heading', { level: 1, name: TITLE })
    expect(screen.queryByRole('button', { name: 'Sustituir ontología' })).not.toBeInTheDocument()
    unmount()
    mockExternal({ role: 'admin' })
    await renderLoggedIn(ROUTE)
    await screen.findByRole('heading', { level: 1, name: TITLE })
    const group = screen.getByRole('group', { name: 'Acciones de la ontología externa' })
    expect(within(group).getAllByRole('button')).toHaveLength(1)
    expect(within(group).getByRole('button', { name: 'Sustituir ontología' })).toHaveClass('button--primary')
  })
})

describe('Sustituir ontología externa (decisión 51)', () => {
  it('diálogo modal: foco en el fichero, campos rellenados, ayuda con la versión n+1 y Escape devuelve el foco', async () => {
    const { dialog, user } = await openDialog()
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByLabelText('Fichero de la ontología (Turtle o JSON-LD)')).toHaveFocus()
    expect(dialog).toHaveAccessibleDescription(
      'Se sustituye la ontología entera por el fichero que subas y se genera la versión 3. Las versiones anteriores no cambian.',
    )
    expect(within(dialog).getByLabelText('Título (en español)')).toHaveValue(TITLE)
    expect(within(dialog).getByLabelText('Descripción (en español, opcional)')).toHaveValue('Descripción de prueba de la externa.')
    expect(within(dialog).getByLabelText('Versión del publicador (opcional)')).toHaveValue('')
    expect(within(dialog).getByLabelText('Prefijo')).toHaveValue('ext')
    expect(within(dialog).getByLabelText('Espacio de nombres')).toHaveValue('https://externa.test/onto#')
    expect(within(dialog).getByLabelText('Publicador (opcional)')).toHaveValue('Publicador externo de prueba')
    expect(within(dialog).getByLabelText('Notas de la versión (en español, opcional)')).toHaveValue('')

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sustituir ontología' })).toHaveFocus()
  })

  it('valida en el cliente fichero, título, prefijo y espacio de nombres sin llamar a la API', async () => {
    const { dialog, user, fetchMock } = await openDialog({ replace: () => jsonResponse(externalReplaceFixture(), 201) })
    await user.clear(within(dialog).getByLabelText('Título (en español)'))
    await user.clear(within(dialog).getByLabelText('Prefijo'))
    await user.type(within(dialog).getByLabelText('Prefijo'), 'Ext-1')
    await user.clear(within(dialog).getByLabelText('Espacio de nombres'))
    await user.type(within(dialog).getByLabelText('Espacio de nombres'), 'no-es-uri')
    await user.click(within(dialog).getByRole('button', { name: 'Sustituir ontología' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Revisa los campos marcados.')
    const file = within(dialog).getByLabelText('Fichero de la ontología (Turtle o JSON-LD)')
    expect(file).toHaveAttribute('aria-invalid', 'true')
    expect(file).toHaveFocus()
    expect(within(dialog).getByLabelText('Título (en español)')).toHaveAccessibleDescription('Este campo es obligatorio.')
    expect(within(dialog).getByLabelText('Prefijo')).toHaveAccessibleDescription(
      expect.stringContaining('Solo minúsculas sin acentos y dígitos, empezando por una letra.'),
    )
    expect(within(dialog).getByLabelText('Espacio de nombres')).toHaveAttribute('aria-invalid', 'true')
    expect(callsTo(fetchMock, 'POST', POST)).toHaveLength(0)
  })

  it('sustituye: manda el multipart, cierra, recarga la ficha y lo anuncia en una región aria-live', async () => {
    let replaced = false
    const after = externalOntologyFixture()
    const v3 = externalVersionFixture({ number: 3, version_info: '3.0-prueba', current: true, notes: 'Notas de la 3.' })
    const { dialog, user, fetchMock } = await openDialog({
      detail: () =>
        jsonResponse(
          replaced
            ? { ...after, version: '3.0-prueba', current_version: v3, versions: [v3, ...after.versions.map((v) => ({ ...v, current: false }))] }
            : after,
        ),
      replace: () => {
        replaced = true
        return jsonResponse(externalReplaceFixture(), 201)
      },
    })
    await user.upload(within(dialog).getByLabelText('Fichero de la ontología (Turtle o JSON-LD)'), new File(['x'], 'ext.jsonld'))
    await user.type(within(dialog).getByLabelText('Versión del publicador (opcional)'), '3.0-prueba')
    await user.type(within(dialog).getByLabelText('Notas de la versión (en español, opcional)'), 'Notas de la 3.')
    await user.click(within(dialog).getByRole('button', { name: 'Sustituir ontología' }))

    const status = await screen.findByText('Ontología sustituida: se ha generado la versión 3, que pasa a ser la actual.')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(await screen.findByText('v3.0-prueba · actual')).toBeInTheDocument()

    const [call] = callsTo(fetchMock, 'POST', POST)
    const body = call[1]?.body as FormData
    expect(body.get('title')).toBe(TITLE)
    expect(body.get('prefix')).toBe('ext')
    expect(body.get('namespace')).toBe('https://externa.test/onto#')
    expect(body.get('publisher')).toBe('Publicador externo de prueba')
    expect(body.get('version_info')).toBe('3.0-prueba')
    expect(body.get('version_notes')).toBe('Notas de la 3.')
    expect((body.get('file') as File).type).toBe('application/ld+json')
    expect(call[1]?.headers).toMatchObject({ Authorization: 'Bearer token-de-prueba' })
  })

  it.each([
    ['409 version_exists', 409, ingestBody('version_exists'), 'Otra persona acaba de sustituir esta ontología; recarga la ficha y vuelve a intentarlo.', null],
    [
      '409 prefix_in_use',
      409,
      ingestBody('prefix_in_use', [
        { message: 'Prefijo en uso', path: null, focus_node: null, value: 'http://uri.test/itot/onto/otra', severity: 'Violation', source_shape: null },
      ]),
      INGEST_KIND_TEXT.prefix_in_use,
      'Prefijo',
    ],
    ['409 prefix_withdrawn', 409, ingestBody('prefix_withdrawn'), INGEST_KIND_TEXT.prefix_withdrawn, 'Prefijo'],
    [
      '422 structure con campo',
      422,
      ingestBody('structure', [
        { message: 'Espacio de nombres no válido', path: 'namespace', focus_node: null, value: null, severity: 'Violation', source_shape: null },
      ]),
      'El fichero no declara la ontología con su IRI oficial (owl:Ontology) o algún campo del formulario no es válido.',
      'Espacio de nombres',
    ],
    ['422 syntax', 422, ingestBody('syntax'), INGEST_KIND_TEXT.syntax, 'Fichero de la ontología (Turtle o JSON-LD)'],
    ['403 por rol', 403, { detail: 'x' }, 'Tu cuenta no tiene permiso para esta acción: hace falta el rol editor o admin.', null],
  ])('%s: mensaje claro dentro del diálogo', async (_case, status, body, message, field) => {
    const { dialog, user } = await openDialog({ replace: () => jsonResponse(body, status) })
    await user.upload(within(dialog).getByLabelText('Fichero de la ontología (Turtle o JSON-LD)'), new File(['x'], 'ext.ttl'))
    await user.click(within(dialog).getByRole('button', { name: 'Sustituir ontología' }))
    await waitFor(() => expect(within(dialog).getByRole('alert')).toHaveTextContent(message))
    if (field) {
      const input = within(dialog).getByLabelText(field)
      expect(input).toHaveAttribute('aria-invalid', 'true')
      expect(input).toHaveFocus()
    }
    expect(screen.getByRole('dialog', { name: 'Sustituir ontología' })).toBeInTheDocument()
  })
})
