import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  accounts,
  api,
  apiPublishOntology,
  apiCreateCatalog,
  ensureExternalVersion,
  EXTERNALS,
  externalDetail,
  externalOntologyTurtle,
  login,
  uniqueSlug,
  type Account,
} from '../support/api'
import { expectNoSeriousA11yViolations } from '../support/a11y'
import { expectNoBrokenText, loginUi, spaGo, ttl, watchConsole } from '../support/ui'

/**
 * Versiones de las ontologías externas (decisión 51) en el navegador: la ficha sin versiones, el
 * diálogo «Sustituir ontología» con teclado y foco, una sustitución completa, los errores del
 * formulario, el historial y `?version=`, la visibilidad por rol y el enlace desde Vocabularios.
 *
 * `d3f` es la externa sin versiones: ninguna prueba la sustituye con éxito. `saref` recibe las
 * sustituciones. Las pruebas calculan el `n` esperado a partir de la API, así que se pueden repetir
 * sobre el mismo entorno. La sesión vive en memoria: se inicia sesión en la aplicación y se navega
 * con `spaGo`, que no recarga.
 */

const D3F = EXTERNALS.d3f
const SAREF = EXTERNALS.saref
const ACTIONS = 'Acciones de la ontología externa'
const L = {
  file: 'Fichero de la ontología (Turtle o JSON-LD)',
  title: 'Título (en español)',
  description: 'Descripción (en español, opcional)',
  versionInfo: 'Versión del publicador (opcional)',
  prefix: 'Prefijo',
  namespace: 'Espacio de nombres',
  publisher: 'Publicador (opcional)',
  notes: 'Notas de la versión (en español, opcional)',
}

async function signIn(page: Page, account: Account, to = '/'): Promise<void> {
  await loginUi(page, account)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  if (to !== '/') await spaGo(page, to)
}

async function openDialog(page: Page): Promise<Locator> {
  await page.getByRole('group', { name: ACTIONS }).getByRole('button', { name: 'Sustituir ontología' }).click()
  const dialog = page.getByRole('dialog', { name: 'Sustituir ontología' })
  await expect(dialog).toBeVisible()
  return dialog
}

function submit(dialog: Locator): Promise<void> {
  return dialog.getByRole('button', { name: 'Sustituir ontología' }).click()
}

async function expectFocusInside(page: Page, dialog: Locator): Promise<void> {
  const inside = await dialog.evaluate((el) => el.contains(document.activeElement))
  expect(inside, 'el foco sale del diálogo').toBe(true)
}

function noteOf(n: number): string {
  return `Notas de la versión ${n} de la prueba de pantallas.`
}

// --- Ficha sin versiones ---------------------------------------------------------------

test('ficha de una externa sin versiones: solo referencia, sin métricas y sin acciones para el anónimo', async ({ page }, testInfo) => {
  const detail = await externalDetail(D3F.slug)
  expect(detail.versions, 'd3f no debe tener versiones: ¿la ha sustituido otra prueba?').toEqual([])
  const check = watchConsole(page)
  await page.goto(`/ontologias/externas/${D3F.slug}`)
  await expect(page.getByRole('heading', { level: 1, name: detail.title ?? '' })).toBeVisible()
  const versioning = page.getByRole('region', { name: 'Versionado' })
  await expect(versioning).toContainText('Todavía no tiene versiones')
  await expect(versioning.getByRole('link', { name: /^Versión \d+$/ })).toHaveCount(0)
  const metrics = page.getByRole('region', { name: 'Métricas' })
  await expect(metrics).toContainText('todavía no se ha sustituido nunca')
  await expect(metrics.getByRole('list', { name: 'Métricas OWL' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: ACTIONS })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Sustituir ontología' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Editar|Dar de baja/ })).toHaveCount(0)
  await expect(page.locator('main')).toContainText(D3F.iri)
  await expectNoBrokenText(page)
  await expectNoSeriousA11yViolations(page, testInfo, 'ficha-externa-sin-versiones')
  check()
})

test('una externa que no existe da «Ontología no encontrada»', async ({ page }) => {
  await page.goto('/ontologias/externas/no-existe')
  await expect(page.getByRole('heading', { level: 1, name: 'Ontología no encontrada' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Volver a Vocabularios' })).toBeVisible()
})

// --- Visibilidad por rol ---------------------------------------------------------------

test('«Sustituir ontología» solo la ven el editor y el admin (no el anónimo ni el miembro)', async ({ page }) => {
  const check = watchConsole(page)
  const path = `/ontologias/externas/${D3F.slug}`
  async function expectButton(visible: boolean): Promise<void> {
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('group', { name: ACTIONS })).toHaveCount(visible ? 1 : 0)
    await expect(page.getByRole('button', { name: 'Sustituir ontología' })).toHaveCount(visible ? 1 : 0)
    // Nunca hay editar ni dar de baja: la API responde 403 not_managed.
    await expect(page.getByRole('button', { name: /^(Editar|Dar de baja|Mover)/ })).toHaveCount(0)
  }
  await page.goto(path)
  await expectButton(false)
  for (const [account, visible] of [
    [accounts().member, false],
    [accounts().editor, true],
    [accounts().admin, true],
  ] as const) {
    await page.goto('/login')
    await loginUi(page, account, 'ya-en-login')
    await spaGo(page, path)
    await expectButton(visible)
  }
  check()
})

// --- Enlace desde Vocabularios ---------------------------------------------------------

test('las tarjetas de las externas en /vocabularios enlazan con /ontologias/externas/{slug}', async ({ page }) => {
  const detail = await externalDetail(D3F.slug)
  const check = watchConsole(page)
  await page.goto('/vocabularios')
  await page.getByRole('group', { name: 'Tipo de vocabulario' }).getByRole('button', { name: 'Ontologías externas' }).click()
  for (const slug of [D3F.slug, SAREF.slug]) {
    const title = (await externalDetail(slug)).title ?? slug
    const card = page.getByRole('link', { name: title, exact: false }).first()
    await expect(card).toHaveAttribute('href', new RegExp(`/ontologias/externas/${slug}$`))
  }
  await page.getByRole('link', { name: detail.title ?? '', exact: false }).first().click()
  await expect(page).toHaveURL(new RegExp(`/ontologias/externas/${D3F.slug}$`))
  await expect(page.getByRole('heading', { level: 1, name: detail.title ?? '' })).toBeVisible()
  check()
})

// --- El diálogo: teclado y foco ----------------------------------------------------------

test('el diálogo es modal, atrapa el foco, se cierra con Escape y devuelve el foco al botón', async ({ page }, testInfo) => {
  const check = watchConsole(page)
  await signIn(page, accounts().editor, `/ontologias/externas/${D3F.slug}`)
  const trigger = page.getByRole('group', { name: ACTIONS }).getByRole('button', { name: 'Sustituir ontología' })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Sustituir ontología' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect(dialog.getByLabel(L.file)).toBeFocused()

  // Las ocho etiquetas y los dos botones.
  for (const label of Object.values(L)) await expect(dialog.getByLabel(label, { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Sustituir ontología' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancelar' })).toBeVisible()
  // Prefijo, espacio de nombres, título y publicador vienen rellenos con los de la referencia.
  const detail = await externalDetail(D3F.slug)
  await expect(dialog.getByLabel(L.prefix, { exact: true })).toHaveValue(detail.prefix ?? '')
  await expect(dialog.getByLabel(L.namespace, { exact: true })).toHaveValue(detail.namespace ?? '')
  await expect(dialog.getByLabel(L.title, { exact: true })).toHaveValue(detail.title ?? '')
  await expectNoSeriousA11yViolations(page, testInfo, 'dialogo-sustituir-ontologia')

  // Tab y Mayús+Tab no sacan el foco del diálogo (se recorre más de una vuelta).
  for (let i = 0; i < 24; i += 1) {
    await page.keyboard.press('Tab')
    await expectFocusInside(page, dialog)
  }
  for (let i = 0; i < 24; i += 1) {
    await page.keyboard.press('Shift+Tab')
    await expectFocusInside(page, dialog)
  }
  // El resto de la página queda fuera: ni el menú lateral recibe el foco.
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()

  // Cancelar también devuelve el foco, y reabrir limpia lo escrito.
  await trigger.click()
  await dialog.getByLabel(L.title, { exact: true }).fill('Título que se descarta')
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await trigger.click()
  await expect(dialog.getByLabel(L.title, { exact: true })).toHaveValue(detail.title ?? '')
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  expect((await externalDetail(D3F.slug)).versions).toEqual([])
  check()
})

test('errores de validación en el cliente: role=alert, aria-invalid y foco en el primer campo con error', async ({ page }, testInfo) => {
  const check = watchConsole(page)
  await signIn(page, accounts().editor, `/ontologias/externas/${D3F.slug}`)
  const dialog = await openDialog(page)

  // Sin fichero: el primer error es el fichero.
  await submit(dialog)
  const alert = dialog.getByRole('alert').first()
  await expect(alert).toContainText('Revisa los campos marcados')
  await expect(dialog.getByLabel(L.file)).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByLabel(L.file)).toBeFocused()

  // Un fichero que no es Turtle ni JSON-LD, título vacío, prefijo y espacio de nombres inválidos.
  await dialog.getByLabel(L.file).setInputFiles({ name: 'notas.txt', mimeType: 'text/plain', buffer: Buffer.from('hola') })
  await dialog.getByLabel(L.title, { exact: true }).fill('')
  await dialog.getByLabel(L.prefix, { exact: true }).fill('Mal Prefijo')
  await dialog.getByLabel(L.namespace, { exact: true }).fill('no es una uri')
  await submit(dialog)
  for (const label of [L.file, L.title, L.prefix, L.namespace]) {
    await expect(dialog.getByLabel(label, { exact: true })).toHaveAttribute('aria-invalid', 'true')
  }
  await expect(dialog.getByLabel(L.description, { exact: true })).not.toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByLabel(L.file)).toBeFocused()
  await expectNoSeriousA11yViolations(page, testInfo, 'dialogo-sustituir-con-errores')

  // Corregido el fichero, el foco salta al siguiente error (el título).
  await dialog.getByLabel(L.file).setInputFiles(ttl('o', externalOntologyTurtle(D3F.iri, 'abc')))
  await submit(dialog)
  await expect(dialog.getByLabel(L.file)).not.toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByLabel(L.title, { exact: true })).toBeFocused()
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  expect((await externalDetail(D3F.slug)).versions).toEqual([])
  check()
})

// --- Errores de la API en el formulario ----------------------------------------------------

test('los errores del backend se muestran en el formulario: syntax y prefix_in_use', async ({ page }) => {
  const check = watchConsole(page, [409, 422])
  const owner = await login(accounts().editor)
  // Un prefijo que ya usa una ontología propia (decisión 50, regla 14).
  const catalog = uniqueSlug('pw51-pref')
  await apiCreateCatalog(owner, catalog, `Catálogo ${catalog}`)
  const own = uniqueSlug('pw51-own')
  const taken = `pw${Math.random().toString(16).slice(2, 8)}`
  await apiPublishOntology(owner, catalog, own, { prefix: taken })
  const before = (await externalDetail(SAREF.slug)).versions.length

  await signIn(page, accounts().editor, `/ontologias/externas/${SAREF.slug}`)
  const dialog = await openDialog(page)

  // 422 syntax: el fichero no es Turtle válido. El error va en la alerta y en el campo del fichero.
  await dialog.getByLabel(L.file).setInputFiles(ttl('roto', 'esto no es turtle {{'))
  await submit(dialog)
  const alert = dialog.getByRole('alert').first()
  await expect(alert).toBeVisible()
  await expect(alert).not.toBeEmpty()
  await expect(dialog.getByLabel(L.file)).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByLabel(L.file)).toBeFocused()
  await expect(dialog).toBeVisible()

  // 409 prefix_in_use: el prefijo es de otra ontología. Error en el campo «Prefijo», con el foco.
  await dialog.getByLabel(L.file).setInputFiles(ttl('bien', externalOntologyTurtle(SAREF.iri, 'pre')))
  await dialog.getByLabel(L.prefix, { exact: true }).fill(taken)
  await submit(dialog)
  await expect(dialog.getByRole('alert').first()).toContainText('ya lo usa otro recurso')
  await expect(dialog.getByLabel(L.prefix, { exact: true })).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByLabel(L.prefix, { exact: true })).toBeFocused()
  await expect(dialog.getByLabel(L.file)).not.toHaveAttribute('aria-invalid', 'true')

  // Corregido el prefijo, el campo deja de estar marcado al reenviar (y se sustituye).
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  await expect(dialog).toHaveCount(0)
  expect((await externalDetail(SAREF.slug)).versions.length, 'los errores no escriben').toBe(before)
  check()
})

// --- Sustitución completa, historial y ?version= ------------------------------------------------

test('sustitución completa: aviso, versión nueva actual, métricas, historial y ?version=', async ({ page }) => {
  const check = watchConsole(page)
  const before = await externalDetail(SAREF.slug)
  const base = before.versions.length
  const title = `Título de la prueba ${uniqueSlug('pw51')}`
  const tag = Math.random().toString(16).slice(2, 8)

  await signIn(page, accounts().editor, `/ontologias/externas/${SAREF.slug}`)

  async function replaceOnce(n: number, extra: { title: string; tag: string; info: string }): Promise<void> {
    const dialog = await openDialog(page)
    await expect(dialog).toContainText(`versión ${n}`)
    await dialog.getByLabel(L.file).setInputFiles(ttl('saref-sintetico', externalOntologyTurtle(SAREF.iri, extra.tag)))
    await dialog.getByLabel(L.title, { exact: true }).fill(extra.title)
    await dialog.getByLabel(L.versionInfo, { exact: true }).fill(extra.info)
    await dialog.getByLabel(L.notes, { exact: true }).fill(noteOf(n))
    await submit(dialog)
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: `Ontología sustituida: se ha generado la versión ${n}, que pasa a ser la actual.` })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`/ontologias/externas/${SAREF.slug}$`))
  }

  await replaceOnce(base + 1, { title, tag, info: '7.1.0' })
  await replaceOnce(base + 2, { title: `${title} (2)`, tag: `${tag}b`, info: '7.2.0' })

  const n = base + 2
  const after = await externalDetail(SAREF.slug)
  expect(after.versions.map((v) => v.number)).toEqual(Array.from({ length: n }, (_, i) => n - i))
  expect(after.current_version?.number).toBe(n)
  await expect(page.getByRole('heading', { level: 1, name: `${title} (2)` })).toBeVisible()

  // Métricas de la versión nueva: las del fichero subido (3 clases).
  const metrics = page.getByRole('region', { name: 'Métricas' })
  const list = metrics.getByRole('list', { name: 'Métricas OWL' })
  await expect(list).toBeVisible()
  await expect(list.getByRole('listitem').filter({ hasText: 'Clases' })).toContainText('3')
  await expect(metrics).toContainText(`versión ${n}`)

  // Historial: cada versión, la mostrada con aria-current, y el RDF descargable de cada una.
  const versioning = page.getByRole('region', { name: 'Versionado' })
  for (const k of [n, n - 1]) {
    await expect(versioning.getByRole('link', { name: `Versión ${k}`, exact: true })).toBeVisible()
    await expect(versioning.getByRole('link', { name: `Descargar el RDF de la versión ${k} (Turtle)` })).toBeVisible()
  }
  await expect(versioning.getByRole('link', { name: `Versión ${n}`, exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(versioning.getByRole('link', { name: `Versión ${n - 1}`, exact: true })).not.toHaveAttribute('aria-current', 'page')
  await expect(page.locator('header').first()).toContainText('actual')

  // La versión anterior: ?version=, aria-current, su cabecera sin «actual» y sus propias métricas.
  await versioning.getByRole('link', { name: `Versión ${n - 1}`, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/ontologias/externas/${SAREF.slug}\\?version=${n - 1}$`))
  await expect(versioning.getByRole('link', { name: `Versión ${n - 1}`, exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(versioning.getByRole('link', { name: `Versión ${n}`, exact: true })).not.toHaveAttribute('aria-current', 'page')
  await expect(metrics).toContainText(`versión ${n - 1}`)
  await expect(page.locator('header').first()).not.toContainText('actual')

  // Los enlaces de descarga apuntan al RDF de cada versión (la actual sin ?version=) y contienen su fichero.
  const oldHref = await versioning.getByRole('link', { name: `Descargar el RDF de la versión ${n - 1} (Turtle)` }).getAttribute('href')
  const newHref = await versioning.getByRole('link', { name: `Descargar el RDF de la versión ${n} (Turtle)` }).getAttribute('href')
  expect(oldHref).toContain(`version=${n - 1}`)
  expect(newHref).not.toContain('version=')
  const oldRdf = await (await page.request.get(oldHref ?? '')).text()
  const newRdf = await (await page.request.get(newHref ?? '')).text()
  expect(oldRdf).toContain(`Marcador${tag}`)
  expect(newRdf).toContain(`Marcador${tag}b`)
  expect(newRdf).not.toContain(`Marcador${tag}>`)

  // Volver a la actual quita ?version=.
  await versioning.getByRole('link', { name: `Versión ${n}`, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/ontologias/externas/${SAREF.slug}$`))
  await expect(versioning.getByRole('link', { name: `Versión ${n}`, exact: true })).toHaveAttribute('aria-current', 'page')

  // Una versión que no existe.
  await spaGo(page, `/ontologias/externas/${SAREF.slug}?version=${n + 50}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Versión no encontrada' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Ver la ficha de la ontología' })).toBeVisible()
  check()
})

test('un lector anónimo ve el historial y la URI de una versión lleva a su ficha (303)', async ({ page }) => {
  const detail = await ensureExternalVersion(await login(accounts().editor), 'saref')
  const n = detail.versions[0].number
  const check = watchConsole(page)
  await page.goto(`/ontologias/externas/${SAREF.slug}?version=${n}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const versioning = page.getByRole('region', { name: 'Versionado' })
  await expect(versioning.getByRole('link', { name: `Versión ${n}`, exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('group', { name: ACTIONS })).toHaveCount(0)

  // La URI persistente de la versión, abierta como un navegador (Accept: text/html), acaba en la ficha.
  const response = await api(`/onto/externas/${SAREF.slug}/${n}`, { headers: { Accept: 'text/html' }, redirect: 'manual' })
  expect(response.status).toBe(303)
  const location = new URL(response.headers.get('location') ?? '')
  expect(location.pathname + location.search).toBe(`/ontologias/externas/${SAREF.slug}?version=${n}`)
  await page.goto(`${location.pathname}${location.search}`)
  await expect(versioning.getByRole('link', { name: `Versión ${n}`, exact: true })).toHaveAttribute('aria-current', 'page')
  check()
})
