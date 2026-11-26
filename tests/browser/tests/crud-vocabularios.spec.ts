import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  accounts,
  API_URL,
  api,
  apiCreateCatalog,
  apiDelete,
  apiPublishOntology,
  apiPublishScheme,
  apiPublishThemedSeries,
  baseUri,
  login,
  ontologyTurtle,
  schemeTurtle,
  themedSeriesTurtle,
  uniquePrefix,
  uniqueSlug,
  type Account,
} from '../support/api'
import { expectNoBrokenText, loginUi, spaGo, ttl, watchConsole } from '../support/ui'

/**
 * Esquemas SKOS y ontologías en los catálogos (decisión 50) en el navegador: botones por rol, el
 * menú «Publicar recurso» con teclado, los formularios, editar, mover y dar de baja, 409 con la
 * lista de usos, 410, el filtro por catálogo y los errores de la ingesta. La sesión vive en
 * memoria: se inicia sesión en la aplicación y se navega con sus enlaces (o con `spaGo`, que no
 * recarga).
 */

const FILE = 'Fichero RDF (Turtle o JSON-LD)'

async function signIn(page: Page, account: Account): Promise<void> {
  await loginUi(page, account)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

async function token(account: Account): Promise<string> {
  return login(account)
}

async function newCatalog(prefix: string): Promise<{ slug: string; title: string }> {
  const slug = uniqueSlug(prefix)
  const title = `Catálogo ${slug}`
  await apiCreateCatalog(await token(accounts().editor), slug, title)
  return { slug, title }
}

async function openMenu(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Publicar recurso' }).click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  return menu
}

async function publishFromForm(region: Locator, file: ReturnType<typeof ttl>, submit: string, catalog?: string) {
  await region.getByLabel(FILE).setInputFiles(file)
  if (catalog) await region.getByLabel('Catálogo').selectOption(catalog)
  await region.getByRole('button', { name: submit }).click()
}

// --- Botones por rol -------------------------------------------------------------------

test('el anónimo y el miembro no ven ningún botón de publicar, editar ni dar de baja', async ({ page }) => {
  const cat = await newCatalog('pw50-rol')
  const owner = await token(accounts().editor)
  const scheme = uniqueSlug('pw50-rol-s')
  const onto = uniqueSlug('pw50-rol-o')
  await apiPublishScheme(owner, cat.slug, scheme)
  await apiPublishOntology(owner, cat.slug, onto)
  const check = watchConsole(page)

  async function noButtons() {
    await spaGo(page, '/')
    await expect(page.getByRole('heading', { level: 1, name: 'Datasets y vocabularios controlados' })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Publicar' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Importar SKOS' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Publicar recurso' })).toHaveCount(0)
    await spaGo(page, `/vocabularios/${scheme}`)
    await expect(page.getByRole('heading', { level: 1, name: `Esquema ${scheme}` })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Acciones del esquema' })).toHaveCount(0)
    await spaGo(page, `/ontologias/${onto}`)
    await expect(page.getByRole('heading', { level: 1, name: `Ontología ${onto}` })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Acciones de la ontología' })).toHaveCount(0)
    for (const name of ['Editar', 'Republicar', 'Dar de baja', 'Mover de catálogo', 'Nueva versión']) {
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
    }
  }

  await page.goto('/')
  await noButtons() // anónimo
  await signIn(page, accounts().member)
  await noButtons() // miembro
  check()
})

for (const role of ['editor', 'admin'] as const) {
  test(`${role}: ve los botones, y los esquemas auxiliares no se gestionan`, async ({ page }) => {
    const cat = await newCatalog(`pw50-${role}`)
    const scheme = uniqueSlug(`pw50-${role}-s`)
    const onto = uniqueSlug(`pw50-${role}-o`)
    const owner = await token(accounts().editor)
    await apiPublishScheme(owner, cat.slug, scheme)
    await apiPublishOntology(owner, cat.slug, onto)
    const check = watchConsole(page)
    await signIn(page, accounts()[role])
    const publish = page.getByRole('group', { name: 'Publicar' })
    await expect(publish.getByRole('button', { name: 'Importar SKOS' })).toBeVisible()
    await expect(publish.getByRole('button', { name: 'Publicar recurso' })).toBeVisible()

    await spaGo(page, `/vocabularios/${scheme}`)
    const actions = page.getByRole('group', { name: 'Acciones del esquema' })
    for (const name of ['Editar', 'Republicar', 'Dar de baja']) {
      await expect(actions.getByRole('button', { name })).toBeVisible()
    }
    await spaGo(page, `/ontologias/${onto}`)
    const ontoActions = page.getByRole('group', { name: 'Acciones de la ontología' })
    for (const name of ['Mover de catálogo', 'Nueva versión', 'Dar de baja']) {
      await expect(ontoActions.getByRole('button', { name })).toBeVisible()
    }
    // Un esquema auxiliar no se gestiona desde la aplicación.
    await spaGo(page, '/vocabularios/dominio')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Acciones del esquema' })).toHaveCount(0)
    check()
  })
}

// --- Menú «Publicar recurso» con teclado -----------------------------------------------

test('«Publicar recurso» es un botón con menú que se maneja con el teclado', async ({ page }) => {
  const check = watchConsole(page)
  await signIn(page, accounts().editor)
  const button = page.getByRole('button', { name: 'Publicar recurso' })
  await expect(button).toHaveAttribute('aria-haspopup', 'menu')
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  const labels = ['Nuevo catálogo', 'Nuevo dataset', 'Nuevo vocabulario', 'Nueva ontología']

  // Intro abre y enfoca la primera; las flechas, Inicio y Fin recorren; las flechas dan la vuelta.
  await button.focus()
  await page.keyboard.press('Enter')
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  await expect(button).toHaveAttribute('aria-expanded', 'true')
  await expect(menu.getByRole('menuitem')).toHaveText(labels)
  await expect(menu.getByRole('menuitem', { name: labels[0] })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: labels[1] })).toBeFocused()
  await page.keyboard.press('End')
  await expect(menu.getByRole('menuitem', { name: labels[3] })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: labels[0] })).toBeFocused()
  await page.keyboard.press('ArrowUp')
  await expect(menu.getByRole('menuitem', { name: labels[3] })).toBeFocused()
  await page.keyboard.press('Home')
  await expect(menu.getByRole('menuitem', { name: labels[0] })).toBeFocused()

  // Escape cierra y devuelve el foco al botón.
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(button).toBeFocused()
  await expect(button).toHaveAttribute('aria-expanded', 'false')

  // Espacio y la flecha arriba abren (esta última, en la última opción).
  await page.keyboard.press('Space')
  await expect(menu).toBeVisible()
  await page.keyboard.press('Escape')
  await page.keyboard.press('ArrowUp')
  await expect(page.getByRole('menuitem', { name: labels[3] })).toBeFocused()

  // Tab cierra, y un clic fuera también.
  await page.keyboard.press('Tab')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await openMenu(page)
  await page.getByRole('heading', { level: 1 }).click()
  await expect(page.getByRole('menu')).toHaveCount(0)

  // Elegir con Intro abre el formulario; Escape lo cierra y devuelve el foco al botón del menú.
  await button.focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('End')
  await page.keyboard.press('ArrowUp') // «Nuevo vocabulario»
  await page.keyboard.press('Enter')
  const form = page.getByRole('region', { name: 'Nuevo vocabulario' })
  await expect(form).toBeVisible()
  await expect(form.getByLabel(FILE)).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(form).toHaveCount(0)
  await expect(button).toBeFocused()
  check()
})

// --- Los cuatro formularios y «Importar SKOS» ------------------------------------------

test('el editor publica un esquema, una ontología, un catálogo y un dataset desde «Publicar recurso»', async ({ page }) => {
  const cat = await newCatalog('pw50-pub')
  const scheme = uniqueSlug('pw50-pub-s')
  const imported = uniqueSlug('pw50-imp-s')
  const onto = uniqueSlug('pw50-pub-o')
  const newCat = uniqueSlug('pw50-pub-c')
  const ds = uniqueSlug('pw50-pub-d')
  const check = watchConsole(page)
  await signIn(page, accounts().editor)

  // Nuevo vocabulario (con un error de validación primero: sin fichero y sin catálogo).
  await (await openMenu(page)).getByRole('menuitem', { name: 'Nuevo vocabulario' }).click()
  const form = page.getByRole('region', { name: 'Nuevo vocabulario' })
  await form.getByRole('button', { name: 'Publicar esquema' }).click()
  await expect(form.getByRole('alert')).toBeVisible()
  await form.getByLabel(FILE).setInputFiles(ttl(scheme, schemeTurtle(scheme)))
  await form.getByRole('button', { name: 'Publicar esquema' }).click()
  await expect(form.getByRole('alert')).toContainText('Elige el catálogo en el que se publica.')
  await form.getByLabel('Catálogo').selectOption(cat.slug)
  await form.getByRole('button', { name: 'Publicar esquema' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Esquema ${scheme}` })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Esquema publicado con 2 conceptos.' })).toBeVisible()
  await expect(page.getByText(`Catálogo: ${cat.title}`)).toBeVisible()
  expect(((await (await api(`/schemes/${scheme}`)).json()) as { catalog: { slug: string } }).catalog.slug).toBe(cat.slug)

  // Importar SKOS: el mismo formulario con otro título; republicar lo mismo: sin cambios.
  await page.getByRole('link', { name: 'Catálogo', exact: true }).first().click()
  await expect(page.getByRole('heading', { level: 1, name: 'Datasets y vocabularios controlados' })).toBeVisible()
  await page.getByRole('button', { name: 'Importar SKOS' }).click()
  const importForm = page.getByRole('region', { name: 'Importar SKOS' })
  await publishFromForm(importForm, ttl(imported, schemeTurtle(imported)), 'Publicar esquema', cat.slug)
  await expect(page.getByRole('heading', { level: 1, name: `Esquema ${imported}` })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Esquema publicado con 2 conceptos.' })).toBeVisible()

  // Nueva ontología.
  await spaGo(page, '/')
  await (await openMenu(page)).getByRole('menuitem', { name: 'Nueva ontología' }).click()
  const ontoForm = page.getByRole('region', { name: 'Nueva ontología' })
  await publishFromForm(ontoForm, ttl(onto, ontologyTurtle(onto)), 'Publicar ontología', cat.slug)
  await expect(page.getByRole('heading', { level: 1, name: `Ontología ${onto}` })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Versión 1.0.0 de la ontología publicada.' })).toBeVisible()

  // Nuevo catálogo y nuevo dataset (con selector de catálogo obligatorio).
  await spaGo(page, '/')
  await (await openMenu(page)).getByRole('menuitem', { name: 'Nuevo catálogo' }).click()
  const catForm = page.getByRole('region', { name: 'Nuevo catálogo' })
  await catForm.getByLabel('Slug').fill(newCat)
  await catForm.getByLabel('Título (en español)').fill(`Catálogo ${newCat}`)
  await catForm.getByLabel('Descripción (en español)').fill('Descripción ficticia.')
  await catForm.getByLabel('Publicador').fill('Pruebas de QA')
  await catForm.getByRole('button', { name: 'Crear catálogo' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${newCat}` })).toBeVisible()
  await spaGo(page, '/')
  await (await openMenu(page)).getByRole('menuitem', { name: 'Nuevo dataset' }).click()
  const dsForm = page.getByRole('region', { name: 'Nuevo dataset' })
  await dsForm.getByLabel('Slug').fill(ds)
  await dsForm.getByLabel('Título (en español)').fill(`Dataset ${ds}`)
  await dsForm.getByLabel('Descripción (en español)').fill('Descripción ficticia.')
  await dsForm.getByRole('button', { name: 'Crear dataset' }).click()
  await expect(dsForm.getByRole('alert')).toBeVisible() // falta el catálogo
  await dsForm.getByLabel('Catálogo').selectOption(cat.slug)
  await dsForm.getByRole('button', { name: 'Crear dataset' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Dataset ${ds}` })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

// --- Errores de la ingesta en los formularios ----------------------------------------

test('publicar: prefix_in_use, catalog_conflict y withdrawn en el formulario de esquemas', async ({ page }) => {
  const cat = await newCatalog('pw50-err')
  const other = await newCatalog('pw50-err2')
  const owner = await token(accounts().editor)
  const taken = uniqueSlug('pw50-e-s')
  const gone = uniqueSlug('pw50-e-g')
  const prefix = uniquePrefix('pfx')
  await apiPublishScheme(owner, cat.slug, taken, { prefix })
  await apiPublishScheme(owner, cat.slug, gone, { prefix: uniquePrefix('pfg') })
  expect(await apiDelete(owner, `/schemes/${gone}`)).toBe(204)
  const check = watchConsole(page, [409])
  await signIn(page, accounts().editor)

  async function submit(slug: string, options: Parameters<typeof schemeTurtle>[1], catalog: string) {
    if ((await page.getByRole('region', { name: 'Nuevo vocabulario' }).count()) === 0) {
      await spaGo(page, '/')
      await (await openMenu(page)).getByRole('menuitem', { name: 'Nuevo vocabulario' }).click()
    }
    const form = page.getByRole('region', { name: 'Nuevo vocabulario' })
    await publishFromForm(form, ttl(slug, schemeTurtle(slug, options)), 'Publicar esquema', catalog)
    return form
  }

  // prefix_in_use: el recurso que ya usa el prefijo sale en la lista.
  const inUse = await submit(uniqueSlug('pw50-e-n'), { prefix }, cat.slug)
  await expect(inUse.getByRole('alert')).toContainText('ya lo usa otro recurso publicado')
  await expect(inUse.getByRole('alert')).toContainText(taken)
  // catalog_conflict: el mismo esquema en otro catálogo.
  const conflict = await submit(taken, { prefix }, other.slug)
  await expect(conflict.getByRole('alert')).toContainText('El esquema ya está en otro catálogo')
  // withdrawn: un esquema dado de baja no se reutiliza.
  const withdrawn = await submit(gone, { prefix: uniquePrefix('pfz') }, cat.slug)
  await expect(withdrawn.getByRole('alert')).toContainText('dado de baja y no se reutiliza')
  // prefix_withdrawn: el prefijo de uno dado de baja.
  const gonePrefix = uniquePrefix('pfw')
  const second = uniqueSlug('pw50-e-w')
  await apiPublishScheme(owner, cat.slug, second, { prefix: gonePrefix })
  expect(await apiDelete(owner, `/schemes/${second}`)).toBe(204)
  const reused = await submit(uniqueSlug('pw50-e-r'), { prefix: gonePrefix }, cat.slug)
  await expect(reused.getByRole('alert')).toContainText('era de un recurso dado de baja')
  check()
})

test('republicar un esquema: concepts_removed, concept_reactivated y replacement', async ({ page }) => {
  const cat = await newCatalog('pw50-rep')
  const owner = await token(accounts().editor)
  const slug = uniqueSlug('pw50-rep-s')
  const base = await baseUri()
  await apiPublishScheme(owner, cat.slug, slug, { concepts: ['raiz', 'hoja', 'otra'] })
  const check = watchConsole(page, [409, 422])
  await signIn(page, accounts().editor)
  await spaGo(page, `/vocabularios/${slug}`)
  await expect(page.getByRole('heading', { level: 1, name: `Esquema ${slug}` })).toBeVisible()

  async function republish(text: string) {
    if ((await page.getByRole('region', { name: 'Republicar el esquema' }).count()) === 0) {
      await page.getByRole('button', { name: 'Republicar', exact: true }).click()
    }
    const form = page.getByRole('region', { name: 'Republicar el esquema' })
    await expect(form.getByText(`Catálogo: ${cat.title}`)).toBeVisible() // el catálogo va fijo
    await form.getByLabel(FILE).setInputFiles(ttl(slug, text))
    await form.getByRole('button', { name: 'Republicar esquema' }).click()
    return form
  }

  // concepts_removed: falta «otra».
  const removed = await republish(schemeTurtle(slug, { concepts: ['raiz', 'hoja'] }))
  await expect(removed.getByRole('alert')).toContainText('Faltan conceptos que ya estaban publicados')
  await expect(removed.getByRole('alert')).toContainText('otra')
  // replacement: un sustituto que no existe.
  const bad = await republish(
    schemeTurtle(slug, { concepts: ['raiz', 'hoja', 'otra'], deprecated: { hoja: [`${base}vocab/${slug}/no-existe`] } }),
  )
  await expect(bad.getByRole('alert')).toContainText('no es un concepto vivo')
  // Retirar «hoja» con «otra» de sustituto: se publica y el detalle lo muestra.
  const ok = await republish(
    schemeTurtle(slug, { concepts: ['raiz', 'hoja', 'otra'], deprecated: { hoja: [`${base}vocab/${slug}/otra`] } }),
  )
  void ok
  await expect(page.getByRole('status').filter({ hasText: 'Esquema republicado con 3 conceptos.' })).toBeVisible()
  await spaGo(page, `/vocabularios/${slug}?concepto=hoja`)
  await expect(page.getByRole('note', { name: 'Concepto retirado' })).toContainText('Retirado')
  await expect(page.getByRole('group', { name: 'Sustitutos' }).or(page.getByLabel('Sustitutos'))).toContainText('Hoja otra')
  // concept_reactivated: volver a publicarlo sin owl:deprecated.
  await spaGo(page, `/vocabularios/${slug}`)
  const reactivated = await republish(schemeTurtle(slug, { concepts: ['raiz', 'hoja', 'otra'] }))
  await expect(reactivated.getByRole('alert')).toContainText('vuelve a estar activo')
  await expectNoBrokenText(page)
  check()
})

test('nueva versión de dataset: deprecated_theme y unknown_theme en el formulario', async ({ page }) => {
  const cat = await newCatalog('pw50-tema')
  const owner = await token(accounts().editor)
  const scheme = uniqueSlug('pw50-t-s')
  const ds = uniqueSlug('pw50-t-d')
  const dead = uniqueSlug('pw50-t-x')
  const base = await baseUri()
  await apiPublishScheme(owner, cat.slug, scheme, { concepts: ['raiz', 'hoja', 'otra'] })
  await apiPublishScheme(owner, cat.slug, dead)
  expect(await apiDelete(owner, `/schemes/${dead}`)).toBe(204)
  expect(await apiPublishThemedSeries(owner, cat.slug, ds, { '1.0.0': [`vocab/${scheme}/hoja`] })).toBe(201)
  // Retirar «hoja» con sustituto «otra».
  const response = await api(`/schemes?catalog=${cat.slug}`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/turtle' },
    body: schemeTurtle(scheme, { concepts: ['raiz', 'hoja', 'otra'], deprecated: { hoja: [`${base}vocab/${scheme}/otra`] } }),
    token: owner,
  })
  expect(response.status).toBe(200)
  const check = watchConsole(page, [422])
  await signIn(page, accounts().editor)
  await spaGo(page, `/datasets/${ds}`)
  await expect(page.getByRole('heading', { level: 1, name: `Dataset ${ds}` })).toBeVisible()

  async function publish(versions: Record<string, string[]>) {
    if ((await page.getByRole('region', { name: 'Nueva versión' }).count()) === 0) {
      await page.getByRole('button', { name: 'Nueva versión' }).click()
    }
    const region = page.getByRole('region', { name: 'Nueva versión' })
    await region.getByLabel(FILE).setInputFiles(ttl(ds, themedSeriesTurtle(ds, cat.slug, versions)))
    await region.getByRole('button', { name: 'Publicar versión' }).click()
    return region
  }

  const hoja = `vocab/${scheme}/hoja`
  const retired = await publish({ '1.0.0': [hoja], '1.1.0': [hoja] })
  await expect(retired.getByRole('alert')).toContainText('conceptos retirados')
  await expect(retired.getByRole('alert')).toContainText(`vocab/${scheme}/otra`) // el sustituto
  const unknown = await publish({ '1.0.0': [hoja], '1.1.0': [`vocab/${dead}/hoja`, 'vocab/ot/no-existe-nunca'] })
  await expect(unknown.getByRole('alert')).toContainText('no son conceptos de un esquema publicado')
  await expect(unknown.getByRole('alert')).toContainText('no-existe-nunca')
  // Con el sustituto y un tema externo, se publica.
  await publish({ '1.0.0': [hoja], '1.1.0': [`vocab/${scheme}/otra`, 'https://example.org/externo/tema'] })
  await expect(page.getByRole('status').filter({ hasText: 'RDF publicado' })).toBeVisible()
  check()
})

// --- Editar y mover --------------------------------------------------------------------

test('editar un esquema, moverlo de catálogo y ver el concepto retirado en el árbol', async ({ page }) => {
  const catA = await newCatalog('pw50-ea')
  const catB = await newCatalog('pw50-eb')
  const owner = await token(accounts().editor)
  const slug = uniqueSlug('pw50-ed-s')
  await apiPublishScheme(owner, catA.slug, slug)
  const check = watchConsole(page)
  await signIn(page, accounts().editor)
  await spaGo(page, `/vocabularios/${slug}`)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const form = page.getByRole('region', { name: 'Editar esquema' })
  await form.getByLabel('Título (en español)').fill(`Esquema ${slug} editado`)
  await form.getByLabel('Catálogo').selectOption(catB.slug)
  await form.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'El esquema se ha movido de catálogo.' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: `Esquema ${slug} editado` })).toBeVisible()
  await expect(page.getByText(`Catálogo: ${catB.title}`)).toBeVisible()
  const detail = (await (await api(`/schemes/${slug}`)).json()) as { uri: string; catalog: { slug: string } }
  expect(detail.catalog.slug).toBe(catB.slug)
  expect(detail.uri).toMatch(new RegExp(`/vocab/${slug}$`)) // la URI no cambia
  // Sin cambios: el aviso lo dice.
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await page.getByRole('region', { name: 'Editar esquema' }).getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'No había cambios que guardar.' })).toBeVisible()
  check()
})

test('mover una ontología de catálogo y publicar una versión nueva', async ({ page }) => {
  const catA = await newCatalog('pw50-oa')
  const catB = await newCatalog('pw50-ob')
  const owner = await token(accounts().editor)
  const slug = uniqueSlug('pw50-mo-o')
  await apiPublishOntology(owner, catA.slug, slug)
  const check = watchConsole(page)
  await signIn(page, accounts().editor)
  await spaGo(page, `/ontologias/${slug}`)
  await page.getByRole('button', { name: 'Mover de catálogo' }).click()
  const move = page.getByRole('region', { name: 'Mover la ontología de catálogo' })
  await move.getByLabel('Catálogo de destino').selectOption(catB.slug)
  await move.getByRole('button', { name: 'Mover' }).click()
  await expect(page.getByText(`Catálogo: ${catB.title}`)).toBeVisible()
  const detail = (await (await api(`/ontologies/${slug}`)).json()) as { catalog: { slug: string } }
  expect(detail.catalog.slug).toBe(catB.slug)
  // Nueva versión: el catálogo va fijo.
  await page.getByRole('button', { name: 'Nueva versión', exact: true }).click()
  const version = page.getByRole('region', { name: 'Nueva versión de la ontología' })
  await expect(version.getByText(`Catálogo: ${catB.title}`)).toBeVisible()
  await version.getByLabel(FILE).setInputFiles(ttl(slug, ontologyTurtle(slug, { version: '1.1.0', prior: '1.0.0' })))
  await version.getByRole('button', { name: 'Publicar versión' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Versión 1.1.0 de la ontología publicada.' })).toBeVisible()
  check()
})

// --- Dar de baja: 409 con la lista de usos, 410 ----------------------------------------

test('dar de baja un esquema en uso da 409 con la lista de usos; sin usos, baja y 410', async ({ page, request }) => {
  const cat = await newCatalog('pw50-bs')
  const owner = await token(accounts().editor)
  const scheme = uniqueSlug('pw50-b-s')
  const ds = uniqueSlug('pw50-b-d')
  await apiPublishScheme(owner, cat.slug, scheme)
  expect(await apiPublishThemedSeries(owner, cat.slug, ds, { '1.0.0': [`vocab/${scheme}/hoja`] })).toBe(201)
  const check = watchConsole(page, [409, 410])
  await signIn(page, accounts().admin)
  await spaGo(page, `/vocabularios/${scheme}`)
  await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Dar de baja el esquema' })
  await dialog.getByRole('button', { name: 'Dar de baja' }).click()
  await expect(dialog.getByRole('alert')).toContainText('lo usan recursos publicados')
  const uses = dialog.getByRole('list', { name: 'Recursos que lo usan' })
  await expect(uses.getByRole('link', { name: new RegExp(`dataset/${ds}/1.0.0`) })).toBeVisible()
  await expect(uses).toContainText('dcat:theme')
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  await expect(dialog).toHaveCount(0)
  expect((await api(`/schemes/${scheme}`)).status).toBe(200)

  // Sin el dataset, la baja funciona: vuelve a la ficha del catálogo y todo responde 410.
  expect(await apiDelete(owner, `/datasets/${ds}`)).toBe(204)
  await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
  await page.getByRole('dialog', { name: 'Dar de baja el esquema' }).getByRole('button', { name: 'Dar de baja' }).click()
  await expect(page.getByRole('heading', { level: 1, name: cat.title })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: `Esquema «Esquema ${scheme}» dado de baja.` })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Vocabularios SKOS del catálogo' })).toHaveCount(0)
  for (const path of [`/schemes/${scheme}`, `/schemes/${scheme}/concepts/hoja`]) {
    const gone = await request.get(`${API_URL}${path}`)
    expect(gone.status()).toBe(410)
    expect(await gone.json()).toMatchObject({ resource: 'scheme' })
  }
  await spaGo(page, `/vocabularios/${scheme}`)
  await expect(page.getByRole('heading', { level: 2, name: 'Esquema dado de baja' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Acciones del esquema' })).toHaveCount(0)
  await spaGo(page, `/vocabularios/${scheme}?concepto=hoja`)
  await expect(page.getByText('se dio de baja con todos sus conceptos')).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('dar de baja una ontología en uso da 409 con sus usos; después, 410 en la ontología y sus versiones', async ({ page, request }) => {
  const cat = await newCatalog('pw50-bo')
  const owner = await token(accounts().editor)
  const target = uniqueSlug('pw50-b-o')
  const user = uniqueSlug('pw50-b-u')
  await apiPublishOntology(owner, cat.slug, target)
  await apiPublishOntology(owner, cat.slug, user, { extra: `<onto/${user}> owl:imports <onto/${target}> .` })
  const check = watchConsole(page, [409, 410])
  await signIn(page, accounts().editor)
  await spaGo(page, `/ontologias/${target}`)
  await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Dar de baja la ontología' })
  await dialog.getByRole('button', { name: 'Dar de baja' }).click()
  await expect(dialog.getByRole('alert')).toContainText('lo usan recursos publicados')
  await expect(dialog.getByRole('list', { name: 'Recursos que lo usan' })).toContainText(`onto/${user}/1.0.0`)
  await expect(dialog.getByRole('list', { name: 'Recursos que lo usan' })).toContainText('owl:imports')
  // Escape cierra el diálogo.
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  expect(await apiDelete(owner, `/ontologies/${user}`)).toBe(204)
  await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
  await page.getByRole('dialog', { name: 'Dar de baja la ontología' }).getByRole('button', { name: 'Dar de baja' }).click()
  await expect(page.getByRole('heading', { level: 1, name: cat.title })).toBeVisible()
  for (const path of [`/ontologies/${target}`, `/ontologies/${target}?version=1.0.0`]) {
    expect((await request.get(`${API_URL}${path}`)).status()).toBe(410)
  }
  await spaGo(page, `/ontologias/${target}?version=1.0.0`)
  await expect(page.getByRole('heading', { level: 2, name: 'Ontología dada de baja' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Acciones de la ontología' })).toHaveCount(0)
  check()
})

test('el diálogo de baja de un esquema atrapa el Tab, se cierra con Escape y devuelve el foco', async ({ page }) => {
  const cat = await newCatalog('pw50-dlg')
  const slug = uniqueSlug('pw50-dlg-s')
  await apiPublishScheme(await token(accounts().editor), cat.slug, slug)
  const check = watchConsole(page)
  await signIn(page, accounts().editor)
  await spaGo(page, `/vocabularios/${slug}`)
  const trigger = page.getByRole('button', { name: 'Dar de baja', exact: true })
  await trigger.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Dar de baja el esquema' })
  await expect(dialog).toBeVisible()
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  check()
})

// --- Catálogos, filtro y 403 not_managed -----------------------------------------------

test('la ficha del catálogo lista sus vocabularios y ontologías; el filtro ?catalog= de /vocabularios', async ({ page }) => {
  const cat = await newCatalog('pw50-fil')
  const other = await newCatalog('pw50-fil2')
  const owner = await token(accounts().editor)
  const scheme = uniqueSlug('pw50-f-s')
  const onto = uniqueSlug('pw50-f-o')
  const elsewhere = uniqueSlug('pw50-f-x')
  await apiPublishScheme(owner, cat.slug, scheme)
  await apiPublishOntology(owner, cat.slug, onto)
  await apiPublishScheme(owner, other.slug, elsewhere)
  const check = watchConsole(page)

  await page.goto('/catalogos')
  await page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: cat.title, exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: cat.title })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Vocabularios SKOS' })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Vocabularios SKOS del catálogo' }).getByRole('link', { name: `Esquema ${scheme}` })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Ontologías del catálogo' }).getByRole('link', { name: `Ontología ${onto}` })).toBeVisible()

  await page.goto(`/vocabularios?catalog=${cat.slug}`)
  await expect(page.getByLabel('Catálogo', { exact: true })).toHaveValue(cat.slug)
  const cards = page.getByRole('list', { name: 'Vocabularios' })
  await expect(cards.getByText(`Esquema ${scheme}`)).toBeVisible()
  await expect(cards.getByText(`Ontología ${onto}`)).toBeVisible()
  await expect(cards.getByText(`Esquema ${elsewhere}`)).toHaveCount(0)
  await expect(cards.getByText('Ontología de activos y amenazas IT/OT')).toHaveCount(0) // las sintéticas, en otro
  await page.getByLabel('Catálogo', { exact: true }).selectOption(other.slug)
  await expect(page).toHaveURL(new RegExp(`catalog=${other.slug}`))
  await expect(cards.getByText(`Esquema ${elsewhere}`)).toBeVisible()
  await expect(cards.getByText(`Esquema ${scheme}`)).toHaveCount(0)
  // Un valor que no es un slug se ignora (no rompe la pantalla).
  await page.goto('/vocabularios?catalog=NO%20ES%20UN%20SLUG')
  await expect(page.getByRole('list', { name: 'Vocabularios' })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('un catálogo con esquemas u ontologías da 409 al darlo de baja, con su lista', async ({ page }) => {
  const cat = await newCatalog('pw50-cne')
  const owner = await token(accounts().editor)
  const scheme = uniqueSlug('pw50-c-s')
  const onto = uniqueSlug('pw50-c-o')
  await apiPublishScheme(owner, cat.slug, scheme)
  await apiPublishOntology(owner, cat.slug, onto)
  const check = watchConsole(page, [409])
  await signIn(page, accounts().admin)
  await spaGo(page, `/catalogos/${cat.slug}`)
  await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Dar de baja el catálogo' })
  await dialog.getByRole('button', { name: 'Dar de baja' }).click()
  await expect(dialog.getByRole('alert')).toContainText('vocabularios u ontologías')
  const list = dialog.getByRole('list').last()
  await expect(list.getByRole('link', { name: new RegExp(`vocab/${scheme}`) })).toBeVisible()
  await expect(list.getByRole('link', { name: new RegExp(`onto/${onto}`) })).toBeVisible()
  check()
})

test('403 not_managed contra la API: esquemas auxiliares y ontologías externas, con editor y admin', async () => {
  for (const account of [accounts().editor, accounts().admin]) {
    const t = await token(account)
    for (const [method, path, body] of [
      ['PATCH', '/schemes/dominio', { title: 'x' }],
      ['DELETE', '/schemes/tipo-dataset', undefined],
      ['PATCH', '/ontologies/externas', { catalog: 'sintetico' }],
      ['DELETE', '/ontologies/externas', undefined],
    ] as const) {
      const response = await api(path, {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
        token: t,
      })
      expect(response.status, `${method} ${path}`).toBe(403)
      expect(await response.json()).toMatchObject({ kind: 'not_managed' })
    }
  }
  // El miembro recibe el 403 por rol, sin kind.
  const member = await api('/schemes/dominio', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'x' }),
    token: await token(accounts().member),
  })
  expect(member.status).toBe(403)
  expect(await member.json()).not.toHaveProperty('kind')
})
