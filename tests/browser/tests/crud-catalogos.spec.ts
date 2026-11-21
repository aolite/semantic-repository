import { expect, test, type Page } from '@playwright/test'
import {
  accounts,
  API_URL,
  api,
  apiCreateCatalog,
  apiCreateDataset,
  apiMoveDataset,
  apiWithdraw,
  login,
  seriesTurtle,
  uniqueSlug,
  type Account,
} from '../support/api'
import { expectNoBrokenText, loginUi, watchConsole } from '../support/ui'

/**
 * CRUD de catálogos y datasets en el navegador (decisión 49): rutas, botones por rol, formularios,
 * 409, 410 y el diálogo de baja con teclado. La sesión vive en memoria: se inicia sesión en la
 * aplicación y se navega con sus enlaces, sin recargar (un `goto` la perdería).
 */

const ONE_VERSION = { '1.0.0': { access: 'PUBLIC', dists: { csv: 'PUBLIC' } } } as const

async function token(account: Account): Promise<string> {
  return login(account)
}

/** Inicia sesión en la aplicación; termina en el catálogo (`/`). */
async function signIn(page: Page, account: Account): Promise<void> {
  await loginUi(page, account)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

/** Del catálogo `/` a la ficha de un catálogo, por los enlaces de la propia aplicación. */
async function openCatalog(page: Page, title: string): Promise<void> {
  await page.getByRole('link', { name: 'Ver los catálogos' }).click()
  await expect(page).toHaveURL(/\/catalogos$/)
  await page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: title, exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
}

async function openDatasetFromCatalog(page: Page, title: string): Promise<void> {
  await page.getByRole('list', { name: 'Datasets del catálogo' }).getByRole('link', { name: title, exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
}

function ttlFile(slug: string, title: string) {
  return {
    name: `${slug}.ttl`,
    mimeType: 'text/turtle',
    buffer: Buffer.from(seriesTurtle(slug, title, ONE_VERSION as never)),
  }
}

// --- Botones por rol ------------------------------------------------------------------

test('el anónimo ve los catálogos y los datasets pero ningún botón de edición', async ({ page }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-anon')
  const ds = uniqueSlug('pw-anon-ds')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
  const check = watchConsole(page)

  await page.goto('/catalogos')
  await expect(page.getByRole('heading', { level: 1, name: 'Catálogos' })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Catálogos' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Nuevo catálogo' })).toHaveCount(0)

  await page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: `Catálogo ${cat}` }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${cat}` })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Acciones del catálogo' })).toHaveCount(0)
  for (const name of ['Editar catálogo', 'Nuevo dataset', 'Dar de baja']) {
    await expect(page.getByRole('button', { name })).toHaveCount(0)
  }
  await openDatasetFromCatalog(page, `Dataset ${ds}`)
  await expect(page.getByRole('group', { name: 'Acciones del dataset' })).toHaveCount(0)
  for (const name of ['Editar', 'Nueva versión', 'Dar de baja']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  check()
})

for (const role of ['member', 'editor', 'admin'] as const) {
  test(`${role}: los botones de edición ${role === 'member' ? 'no se ven' : 'se ven'}`, async ({ page }) => {
    const owner = await token(accounts().editor)
    const cat = uniqueSlug(`pw-${role}`)
    const ds = uniqueSlug(`pw-${role}-ds`)
    await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
    await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
    const expected = role === 'member' ? 0 : 1
    const check = watchConsole(page)

    await signIn(page, accounts()[role])
    await page.getByRole('link', { name: 'Ver los catálogos' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Catálogos' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Nuevo catálogo' })).toHaveCount(expected)
    await page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: `Catálogo ${cat}` }).click()
    await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${cat}` })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Acciones del catálogo' })).toHaveCount(expected)
    for (const name of ['Editar catálogo', 'Nuevo dataset', 'Dar de baja']) {
      await expect(page.getByRole('button', { name })).toHaveCount(expected)
    }
    await openDatasetFromCatalog(page, `Dataset ${ds}`)
    await expect(page.getByRole('group', { name: 'Acciones del dataset' })).toHaveCount(expected)
    for (const name of ['Editar', 'Nueva versión', 'Dar de baja']) {
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(expected)
    }
    check()
  })
}

// --- Crear, editar y publicar -----------------------------------------------------------

test('el editor crea un catálogo y un dataset, los edita y publica una versión (201 y 200)', async ({ page }) => {
  const cat = uniqueSlug('pw-crud')
  const ds = uniqueSlug('pw-crud-ds')
  const check = watchConsole(page)
  await signIn(page, accounts().editor)
  await page.getByRole('link', { name: 'Ver los catálogos' }).click()

  // Nuevo catálogo (con un error de validación primero: el slug es obligatorio).
  await page.getByRole('button', { name: 'Nuevo catálogo' }).click()
  const newCatalog = page.getByRole('region', { name: 'Nuevo catálogo' })
  await newCatalog.getByRole('button', { name: 'Crear catálogo' }).click()
  await expect(newCatalog.getByRole('alert')).toBeVisible()
  await newCatalog.getByLabel('Slug').fill(cat)
  await newCatalog.getByLabel('Título (en español)').fill(`Catálogo ${cat}`)
  await newCatalog.getByLabel('Descripción (en español)').fill('Descripción ficticia.')
  await newCatalog.getByLabel('Publicador').fill('Pruebas de QA')
  await newCatalog.getByRole('button', { name: 'Crear catálogo' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${cat}` })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Catálogo creado.' })).toBeVisible()

  // Editar el catálogo.
  await page.getByRole('button', { name: 'Editar catálogo' }).click()
  const edit = page.getByRole('region', { name: 'Editar catálogo' })
  await edit.getByLabel('Título (en español)').fill(`Catálogo ${cat} editado`)
  await edit.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Cambios guardados.' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${cat} editado` })).toBeVisible()

  // Nuevo dataset en el catálogo.
  await page.getByRole('button', { name: 'Nuevo dataset' }).click()
  const newDataset = page.getByRole('region', { name: 'Nuevo dataset en este catálogo' })
  await newDataset.getByLabel('Slug').fill(ds)
  await newDataset.getByLabel('Título (en español)').fill(`Dataset ${ds}`)
  await newDataset.getByLabel('Descripción (en español)').fill('Descripción ficticia del dataset.')
  await newDataset.getByRole('button', { name: 'Crear dataset' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `Dataset ${ds}` })).toBeVisible()

  // Editar el dataset.
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const editDataset = page.getByRole('region', { name: 'Editar dataset' })
  await editDataset.getByLabel('Título (en español)').fill(`Dataset ${ds} editado`)
  await editDataset.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Cambios guardados.' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: `Dataset ${ds} editado` })).toBeVisible()

  // Nueva versión: la primera vez (201) y, con el mismo fichero, sin cambios (200).
  const file = ttlFile(ds, `Dataset ${ds} editado`)
  await page.getByRole('button', { name: 'Nueva versión' }).click()
  const version = page.getByRole('region', { name: 'Nueva versión' })
  await version.getByLabel('Fichero RDF (Turtle o JSON-LD)').setInputFiles(file)
  await version.getByRole('button', { name: 'Publicar versión' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'RDF publicado. Versiones de la serie: 1.0.0.' })).toBeVisible()
  await page.getByRole('button', { name: 'Nueva versión' }).click()
  const again = page.getByRole('region', { name: 'Nueva versión' })
  await again.getByLabel('Fichero RDF (Turtle o JSON-LD)').setInputFiles(file)
  await again.getByRole('button', { name: 'Publicar versión' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'El RDF era idéntico al publicado' })).toBeVisible()

  // Cancelar cierra el panel.
  await page.getByRole('button', { name: 'Nueva versión' }).click()
  await page.getByRole('region', { name: 'Nueva versión' }).getByRole('button', { name: 'Cancelar' }).click()
  await expect(page.getByRole('region', { name: 'Nueva versión' })).toHaveCount(0)
  await expectNoBrokenText(page)
  check()
})

test('nueva versión: 409 version_immutable, catalog_conflict y withdrawn en el formulario', async ({ page }) => {
  const owner = await token(accounts().editor)
  const catA = uniqueSlug('pw-va')
  const catB = uniqueSlug('pw-vb')
  const ds = uniqueSlug('pw-v-ds')
  const other = uniqueSlug('pw-v-otro')
  const gone = uniqueSlug('pw-v-baja')
  await apiCreateCatalog(owner, catA, `Catálogo ${catA}`)
  await apiCreateCatalog(owner, catB, `Catálogo ${catB}`)
  await apiCreateDataset(owner, catA, ds, `Dataset ${ds}`)
  await apiCreateDataset(owner, catB, other, `Dataset ${other}`)
  await apiCreateDataset(owner, catA, gone, `Dataset ${gone}`)
  await apiWithdraw(owner, 'datasets', gone)
  const check = watchConsole(page, [409])

  await signIn(page, accounts().editor)
  await openCatalog(page, `Catálogo ${catA}`)
  await openDatasetFromCatalog(page, `Dataset ${ds}`)

  async function publish(file: { name: string; mimeType: string; buffer: Buffer }) {
    if ((await page.getByRole('region', { name: 'Nueva versión' }).count()) === 0) {
      await page.getByRole('button', { name: 'Nueva versión' }).click()
    }
    const region = page.getByRole('region', { name: 'Nueva versión' })
    await region.getByLabel('Fichero RDF (Turtle o JSON-LD)').setInputFiles(file)
    await region.getByRole('button', { name: 'Publicar versión' }).click()
    return region
  }

  // Primero se publica la 1.0.0; después, la misma versión con otro título: version_immutable.
  await publish(ttlFile(ds, `Dataset ${ds}`))
  await expect(page.getByRole('status').filter({ hasText: 'RDF publicado' })).toBeVisible()
  const original = seriesTurtle(ds, `Dataset ${ds}`, ONE_VERSION as never)
  const altered = original.replace(
    /(<dataset\/[^>]+\/1\.0\.0> a dcat:Dataset ; dct:type <[^>]+> ;\n {4}dct:title )"[^"]+"/,
    '$1"Título alterado"',
  )
  expect(altered).not.toBe(original)
  const immutable = await publish({ name: 'x.ttl', mimeType: 'text/turtle', buffer: Buffer.from(altered) })
  await expect(immutable.getByRole('alert')).toContainText('Una versión ya publicada viene con otro contenido')

  // catalog_conflict: una serie que está en el otro catálogo, publicada desde la ficha de esta.
  const conflict = await publish(ttlFile(other, `Dataset ${other}`))
  await expect(conflict.getByRole('alert')).toContainText('La serie ya está en otro catálogo')

  // withdrawn: el slug de una serie dada de baja no se reutiliza.
  const withdrawn = await publish(ttlFile(gone, `Dataset ${gone}`))
  await expect(withdrawn.getByRole('alert')).toContainText('dado de baja y no se reutiliza')
  check()
})

// --- 409 al dar de baja un catálogo con datasets, 410 y 409 por slug --------------------------

test('dar de baja un catálogo con datasets da 409 con su lista; vacío, 410', async ({ page, request }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-409')
  const ds = uniqueSlug('pw-409-ds')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
  const check = watchConsole(page, [409])

  await signIn(page, accounts().admin)
  await openCatalog(page, `Catálogo ${cat}`)
  await page.getByRole('button', { name: 'Dar de baja' }).click()
  const dialog = page.getByRole('dialog', { name: 'Dar de baja el catálogo' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Dar de baja' }).click()
  await expect(dialog.getByRole('alert')).toContainText('El catálogo todavía tiene datasets')
  const remaining = dialog.getByRole('list', { name: 'Datasets que siguen en el catálogo' })
  await expect(remaining.getByRole('link', { name: ds })).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancelar' }).click()
  await expect(dialog).toHaveCount(0)
  expect((await api(`/catalogs/${cat}`)).status).toBe(200) // sigue vivo

  // Sin datasets (el dataset se da de baja por la API), la baja funciona.
  await apiWithdraw(owner, 'datasets', ds)
  await page.getByRole('button', { name: 'Dar de baja' }).click()
  await page.getByRole('dialog', { name: 'Dar de baja el catálogo' }).getByRole('button', { name: 'Dar de baja' }).click()
  await expect(page).toHaveURL(/\/catalogos$/)
  await expect(page.getByRole('status').filter({ hasText: `Catálogo «Catálogo ${cat}» dado de baja.` })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: `Catálogo ${cat}` })).toHaveCount(0)
  expect((await request.get(`${API_URL}/catalogs/${cat}`)).status()).toBe(410)
  check()
})

test('un dataset y un catálogo dados de baja responden 410 en la API y en la ficha', async ({ page, request }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-410')
  const emptyCat = uniqueSlug('pw-410-c')
  const ds = uniqueSlug('pw-410-ds')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateCatalog(owner, emptyCat, `Catálogo vacío ${emptyCat}`)
  await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
  await apiWithdraw(owner, 'datasets', ds)
  await apiWithdraw(owner, 'catalogs', emptyCat)

  const dsApi = await request.get(`${API_URL}/datasets/${ds}`)
  expect(dsApi.status()).toBe(410)
  expect(await dsApi.json()).toMatchObject({ resource: 'dataset', title: `Dataset ${ds}` })
  const catApi = await request.get(`${API_URL}/catalogs/${emptyCat}`)
  expect(catApi.status()).toBe(410)
  expect(await catApi.json()).toMatchObject({ resource: 'catalog' })

  const check = watchConsole(page, [410])
  await page.goto(`/datasets/${ds}`)
  await expect(page.getByRole('heading', { level: 1, name: `Dataset ${ds}` })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Dataset dado de baja' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Acciones del dataset' })).toHaveCount(0)
  await page.goto(`/catalogos/${emptyCat}`)
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo vacío ${emptyCat}` })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Catálogo dado de baja' })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('el slug de un recurso dado de baja no se puede reutilizar desde los formularios (409)', async ({ page }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-slug')
  const goneCat = uniqueSlug('pw-slug-c')
  const goneDs = uniqueSlug('pw-slug-ds')
  const liveDs = uniqueSlug('pw-slug-vivo')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateDataset(owner, cat, liveDs, `Dataset ${liveDs}`)
  await apiCreateCatalog(owner, goneCat, `Catálogo ${goneCat}`)
  await apiCreateDataset(owner, cat, goneDs, `Dataset ${goneDs}`)
  await apiWithdraw(owner, 'datasets', goneDs)
  await apiWithdraw(owner, 'catalogs', goneCat)
  const check = watchConsole(page, [409])

  await signIn(page, accounts().editor)
  await page.getByRole('link', { name: 'Ver los catálogos' }).click()
  await page.getByRole('button', { name: 'Nuevo catálogo' }).click()
  const newCatalog = page.getByRole('region', { name: 'Nuevo catálogo' })
  await newCatalog.getByLabel('Slug').fill(goneCat)
  await newCatalog.getByLabel('Título (en español)').fill('Otro catálogo')
  await newCatalog.getByLabel('Descripción (en español)').fill('Descripción ficticia.')
  await newCatalog.getByLabel('Publicador').fill('Pruebas de QA')
  await newCatalog.getByRole('button', { name: 'Crear catálogo' }).click()
  await expect(newCatalog.getByRole('alert')).toContainText('Ese slug es de un recurso dado de baja y no se reutiliza')
  await newCatalog.getByLabel('Slug').fill(cat)
  await newCatalog.getByRole('button', { name: 'Crear catálogo' }).click()
  await expect(newCatalog.getByRole('alert')).toContainText('Ya existe un recurso con ese slug')

  await newCatalog.getByRole('button', { name: 'Cancelar' }).click()
  await page.getByRole('list', { name: 'Catálogos' }).getByRole('link', { name: `Catálogo ${cat}` }).click()
  await page.getByRole('button', { name: 'Nuevo dataset' }).click()
  const newDataset = page.getByRole('region', { name: 'Nuevo dataset en este catálogo' })
  await newDataset.getByLabel('Slug').fill(goneDs)
  await newDataset.getByLabel('Título (en español)').fill('Otro dataset')
  await newDataset.getByLabel('Descripción (en español)').fill('Descripción ficticia.')
  await newDataset.getByRole('button', { name: 'Crear dataset' }).click()
  await expect(newDataset.getByRole('alert')).toContainText('Ese slug es de un recurso dado de baja y no se reutiliza')

  // Slug en uso (un recurso vivo): el mensaje es otro.
  await newDataset.getByLabel('Slug').fill(liveDs)
  await newDataset.getByRole('button', { name: 'Crear dataset' }).click()
  await expect(newDataset.getByRole('alert')).toContainText('Ya existe un recurso con ese slug')
  await expect(newDataset.getByRole('alert')).not.toContainText('dado de baja')
  check()
})

// --- Rutas ------------------------------------------------------------------------------

test('/catalogo/{slug} redirige con 303 a /catalogos/{slug}; dado de baja, 410', async ({ page, request }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-303')
  const goneCat = uniqueSlug('pw-303-baja')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateCatalog(owner, goneCat, `Catálogo ${goneCat}`)
  await apiWithdraw(owner, 'catalogs', goneCat)

  const redirect = await request.get(`${API_URL}/catalogo/${cat}`, {
    maxRedirects: 0,
    headers: { Accept: 'text/html' },
  })
  expect(redirect.status()).toBe(303)
  expect(redirect.headers()['location']).toMatch(new RegExp(`/catalogos/${cat}$`))
  const gone = await request.get(`${API_URL}/catalogo/${goneCat}`, { maxRedirects: 0, headers: { Accept: 'text/html' } })
  expect(gone.status()).toBe(410)

  await page.goto(`${API_URL}/catalogo/${cat}`)
  await expect(page).toHaveURL(new RegExp(`/catalogos/${cat}$`))
  await expect(page.getByRole('heading', { level: 1, name: `Catálogo ${cat}` })).toBeVisible()
})

test('/?catalogo={slug} filtra el catálogo por catálogo', async ({ page }) => {
  const owner = await token(accounts().editor)
  const catA = uniqueSlug('pw-fa')
  const catB = uniqueSlug('pw-fb')
  const inA = uniqueSlug('pw-f-a')
  const inB = uniqueSlug('pw-f-b')
  await apiCreateCatalog(owner, catA, `Catálogo ${catA}`)
  await apiCreateCatalog(owner, catB, `Catálogo ${catB}`)
  await apiCreateDataset(owner, catA, inA, `Dataset ${inA}`)
  await apiCreateDataset(owner, catB, inB, `Dataset ${inB}`)
  const check = watchConsole(page)

  await page.goto(`/?catalogo=${catA}`)
  await expect(page.getByLabel('Catálogo', { exact: true })).toHaveValue(catA)
  await expect(page.getByRole('link', { name: `Dataset ${inA}` })).toBeVisible()
  await expect(page.getByRole('link', { name: `Dataset ${inB}` })).toHaveCount(0)
  await page.getByLabel('Catálogo', { exact: true }).selectOption(catB)
  await expect(page).toHaveURL(new RegExp(`catalogo=${catB}`))
  await expect(page.getByRole('link', { name: `Dataset ${inB}` })).toBeVisible()
  await expect(page.getByRole('link', { name: `Dataset ${inA}` })).toHaveCount(0)
  check()
})

test('mover un dataset de catálogo desde «Editar»', async ({ page }) => {
  const owner = await token(accounts().editor)
  const catA = uniqueSlug('pw-ma')
  const catB = uniqueSlug('pw-mb')
  const ds = uniqueSlug('pw-m-ds')
  await apiCreateCatalog(owner, catA, `Catálogo ${catA}`)
  await apiCreateCatalog(owner, catB, `Catálogo ${catB}`)
  await apiCreateDataset(owner, catA, ds, `Dataset ${ds}`)
  const check = watchConsole(page)

  await signIn(page, accounts().editor)
  await openCatalog(page, `Catálogo ${catA}`)
  await openDatasetFromCatalog(page, `Dataset ${ds}`)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const edit = page.getByRole('region', { name: 'Editar dataset' })
  await edit.getByLabel('Catálogo').selectOption(catB)
  await edit.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'El dataset se ha movido de catálogo.' })).toBeVisible()
  const detail = (await (await api(`/datasets/${ds}`)).json()) as { uri: string; catalog: { slug: string } | null }
  expect(detail.catalog?.slug).toBe(catB)
  expect(detail.uri).toMatch(new RegExp(`/dataset/${ds}$`)) // la URI no cambia
  check()
  await apiMoveDataset(owner, ds, catA) // la API sigue permitiendo devolverlo
})

test('«Editar dataset» muestra el publicador actual y lo conserva si se deja', async ({ page }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-pub')
  const ds = uniqueSlug('pw-pub-ds')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`, 'Editorial ficticia')
  const check = watchConsole(page)

  await signIn(page, accounts().editor)
  await openCatalog(page, `Catálogo ${cat}`)
  await openDatasetFromCatalog(page, `Dataset ${ds}`)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const edit = page.getByRole('region', { name: 'Editar dataset' })
  await expect(edit.getByLabel('Publicador (opcional)')).toHaveValue('Editorial ficticia')
  await edit.getByLabel('Título (en español)').fill(`Dataset ${ds} editado`)
  await edit.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Cambios guardados.' })).toBeVisible()
  const detail = (await (await api(`/datasets/${ds}`)).json()) as { publisher: { label: string } | null }
  expect(detail.publisher?.label).toBe('Editorial ficticia') // sigue igual

  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const again = page.getByRole('region', { name: 'Editar dataset' })
  await again.getByLabel('Publicador (opcional)').fill('Otra editorial')
  await again.getByRole('button', { name: 'Guardar cambios' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Cambios guardados.' })).toBeVisible()
  expect(((await (await api(`/datasets/${ds}`)).json()) as { publisher: { label: string } }).publisher.label).toBe(
    'Otra editorial',
  )
  check()
})

// --- Baja de un dataset y diálogo con teclado ----------------------------------------------

test('dar de baja un dataset: diálogo, foco, Tab atrapado, Escape y confirmación', async ({ page, request }) => {
  const owner = await token(accounts().editor)
  const cat = uniqueSlug('pw-bd')
  const ds = uniqueSlug('pw-bd-ds')
  await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
  await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
  const check = watchConsole(page)

  await signIn(page, accounts().editor)
  await openCatalog(page, `Catálogo ${cat}`)
  await openDatasetFromCatalog(page, `Dataset ${ds}`)

  const trigger = page.getByRole('group', { name: 'Acciones del dataset' }).getByRole('button', { name: 'Dar de baja' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Dar de baja el dataset' })
  await expect(dialog).toBeVisible()
  const cancel = dialog.getByRole('button', { name: 'Cancelar' })
  const confirm = dialog.getByRole('button', { name: 'Dar de baja' })
  await expect(cancel).toBeFocused() // la opción segura

  await page.keyboard.press('Tab')
  await expect(confirm).toBeFocused()
  await page.keyboard.press('Tab') // el foco no sale del diálogo
  await expect(cancel).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(confirm).toBeFocused()

  await page.keyboard.press('Escape') // cancela y devuelve el foco al botón que lo abrió
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect((await api(`/datasets/${ds}`)).status).toBe(200)

  await trigger.click()
  await page.getByRole('dialog', { name: 'Dar de baja el dataset' }).getByRole('button', { name: 'Dar de baja' }).click()
  await expect(page).toHaveURL(new RegExp(`/catalogos/${cat}$`))
  await expect(page.getByRole('status').filter({ hasText: `Dataset «Dataset ${ds}» dado de baja.` })).toBeVisible()
  await expect(page.getByRole('link', { name: `Dataset ${ds}`, exact: true })).toHaveCount(0)
  expect((await request.get(`${API_URL}/datasets/${ds}`)).status()).toBe(410)
  check()
})
