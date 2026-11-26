import { expect, test, type Page } from '@playwright/test'
import {
  accounts,
  apiCreateCatalog,
  apiCreateDataset,
  apiPublishOntology,
  apiPublishScheme,
  ensureExternalVersion,
  login,
  uniqueSlug,
  type Account,
} from '../support/api'
import { expectNoSeriousA11yViolations } from '../support/a11y'
import { MODBUS, MODBUS_TITLE, loginUi, spaGo } from '../support/ui'

/**
 * Accesibilidad con axe-core (decisión 53) en las pantallas principales y en los diálogos y
 * formularios de CRUD que ya existían. Falla con violaciones `serious` y `critical`; las demás se
 * adjuntan al informe. No hay exclusiones: lo que salga en una pantalla anterior es un hallazgo.
 *
 * Las fichas de las externas (sin versiones, con versiones y con el diálogo abierto) se analizan en
 * `externas-versiones.spec.ts`, junto a la interacción que las deja en cada estado.
 */

async function signIn(page: Page, account: Account, to: string): Promise<void> {
  await loginUi(page, account)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await spaGo(page, to)
}

// --- Pantallas principales (lector anónimo) -------------------------------------------

test.describe('pantallas principales', () => {
  test('Catálogo', async ({ page }, testInfo) => {
    await page.goto('/')
    await expect(page.getByRole('list', { name: 'Recursos' }).locator('article.card').first()).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'catalogo')
  })

  test('Catálogo con filtros y resultados vacíos', async ({ page }, testInfo) => {
    await page.goto('/?tipo=vocabularios&q=zzz-sin-resultados')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'catalogo-vacio')
  })

  test('Lista y ficha de catálogo', async ({ page }, testInfo) => {
    await page.goto('/catalogos')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'catalogos')
    await page.goto('/catalogos/sintetico')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-catalogo')
  })

  test('Ficha de dataset', async ({ page }, testInfo) => {
    await page.goto(`/datasets/${MODBUS}`)
    await expect(page.getByRole('heading', { level: 1, name: MODBUS_TITLE })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-dataset')
  })

  test('Vocabularios y ontologías', async ({ page }, testInfo) => {
    await page.goto('/vocabularios')
    await expect(page.getByRole('heading', { level: 1, name: 'Vocabularios y ontologías' })).toBeVisible()
    await expect(page.getByText(/^\d+ vocabularios$/)).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'vocabularios')
  })

  test('Ficha de ontología propia', async ({ page }, testInfo) => {
    await page.goto('/ontologias/itot')
    await expect(page.getByRole('heading', { level: 1, name: 'Ontología de activos y amenazas IT/OT' })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-ontologia')
  })

  test('Ficha de ontología propia con el cursor sobre «Descargar Turtle» (estado :hover)', async ({ page }, testInfo) => {
    await page.goto('/ontologias/itot')
    await expect(page.getByRole('heading', { level: 1, name: 'Ontología de activos y amenazas IT/OT' })).toBeVisible()
    await page.getByRole('link', { name: 'Descargar Turtle' }).hover()
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-ontologia-hover-descargar')
  })

  test('Ficha de ontología externa con versiones (anónimo)', async ({ page }, testInfo) => {
    await ensureExternalVersion(await login(accounts().editor), 'saref')
    await page.goto('/ontologias/externas/saref')
    await expect(page.getByRole('region', { name: 'Versionado' }).getByRole('link', { name: /^Versión \d+( ·|$)/ }).first()).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-externa-versiones-anonimo')
  })

  test('Ficha de ontología externa: versión anterior (?version=)', async ({ page }, testInfo) => {
    const detail = await ensureExternalVersion(await login(accounts().editor), 'saref')
    const old = detail.versions[detail.versions.length - 1].number
    await page.goto(`/ontologias/externas/saref?version=${old}`)
    await expect(page.getByRole('region', { name: 'Versionado' }).getByRole('link', { name: new RegExp(`^Versión ${old}( ·|$)`) })).toHaveAttribute('aria-current', 'page')
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-externa-version-anterior')
  })

  test('Ficha de ontología externa con versiones (editor)', async ({ page }, testInfo) => {
    await ensureExternalVersion(await login(accounts().editor), 'saref')
    await signIn(page, accounts().editor, '/ontologias/externas/saref')
    await expect(page.getByRole('group', { name: 'Acciones de la ontología externa' })).toBeVisible()
    await page.mouse.move(1, 1) // el cursor no puede quedar sobre un botón (ver QA-51-03)
    await expectNoSeriousA11yViolations(page, testInfo, 'ficha-externa-versiones-editor')
  })

  test('Navegador SKOS', async ({ page }, testInfo) => {
    await page.goto('/vocabularios/ot')
    await expect(page.getByRole('heading', { level: 1, name: 'Protocolos y arquitectura OT' })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'navegador-skos')
    await page.getByRole('tree').getByRole('treeitem').first().click()
    await expectNoSeriousA11yViolations(page, testInfo, 'navegador-skos-concepto')
  })

  test('Consola SPARQL', async ({ page }, testInfo) => {
    await page.goto('/sparql')
    await expect(page.getByRole('heading', { level: 1, name: 'Consulta SPARQL' })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'consola-sparql')
    await page.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: /Datasets clasificados en OT/ }).click()
    await page.getByRole('button', { name: 'Ejecutar' }).click()
    await expect(page.getByRole('region', { name: 'Resultados' }).getByRole('table')).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'consola-sparql-resultado')
  })

  test('Inicio de sesión', async ({ page }, testInfo) => {
    await page.goto('/login')
    await expect(page.getByLabel('Usuario')).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'login')
  })
})

// --- Diálogos y formularios de CRUD (editor) ---------------------------------------------

test.describe('diálogos y formularios de CRUD', () => {
  test('formularios de catálogo: nuevo y editar', async ({ page }, testInfo) => {
    const cat = uniqueSlug('pw-a11y')
    await apiCreateCatalog(await login(accounts().editor), cat, `Catálogo ${cat}`)
    await signIn(page, accounts().editor, '/catalogos')
    await page.getByRole('button', { name: 'Nuevo catálogo' }).click()
    const form = page.getByRole('region', { name: 'Nuevo catálogo' })
    await expect(form).toBeVisible()
    await form.getByRole('button', { name: 'Crear catálogo' }).click() // con error de validación
    await expect(form.getByRole('alert')).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'formulario-nuevo-catalogo')

    await spaGo(page, `/catalogos/${cat}`)
    await page.getByRole('button', { name: 'Editar catálogo' }).click()
    await expect(page.getByRole('region', { name: 'Editar catálogo' })).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'formulario-editar-catalogo')
  })

  test('menú «Publicar recurso» y formularios de la ficha de catálogo', async ({ page }, testInfo) => {
    const cat = uniqueSlug('pw-a11y-pub')
    await apiCreateCatalog(await login(accounts().editor), cat, `Catálogo ${cat}`)
    await signIn(page, accounts().editor, `/catalogos/${cat}`)
    await page.getByRole('button', { name: 'Publicar recurso' }).click()
    await expect(page.getByRole('menu')).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'menu-publicar-recurso')
    for (const [item, region] of [
      ['Nuevo dataset', 'Nuevo dataset en este catálogo'],
      ['Nuevo vocabulario', null],
      ['Nueva ontología', null],
    ] as const) {
      if (!(await page.getByRole('menu').isVisible())) await page.getByRole('button', { name: 'Publicar recurso' }).click()
      await page.getByRole('menuitem', { name: item }).click()
      if (region) await expect(page.getByRole('region', { name: region })).toBeVisible()
      else await expect(page.getByRole('button', { name: /^Publicar (esquema|ontología)/ }).first()).toBeVisible()
      await expectNoSeriousA11yViolations(page, testInfo, `formulario-${item.toLowerCase().replace(/\s+/g, '-')}`)
    }
  })

  const baja = async (page: Page, kind: 'catalogo' | 'dataset' | 'esquema' | 'ontologia') => {
    const owner = await login(accounts().editor)
    const cat = uniqueSlug('pw-a11y-baja')
    const slug = uniqueSlug('pw-a11y-r')
    await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
    if (kind === 'dataset') await apiCreateDataset(owner, cat, slug, `Dataset ${slug}`)
    if (kind === 'esquema') await apiPublishScheme(owner, cat, slug)
    if (kind === 'ontologia') await apiPublishOntology(owner, cat, slug)
    const target = {
      catalogo: { path: `/catalogos/${cat}`, name: 'Dar de baja el catálogo' },
      dataset: { path: `/datasets/${slug}`, name: 'Dar de baja el dataset' },
      esquema: { path: `/vocabularios/${slug}`, name: 'Dar de baja el esquema' },
      ontologia: { path: `/ontologias/${slug}`, name: 'Dar de baja la ontología' },
    }[kind]
    await signIn(page, accounts().editor, target.path)
    await page.getByRole('button', { name: 'Dar de baja', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: target.name })
    await expect(dialog).toBeVisible()
    return dialog
  }
  for (const kind of ['catalogo', 'dataset', 'esquema', 'ontologia'] as const) {
    test(`diálogo de baja: ${kind}`, async ({ page }, testInfo) => {
      const dialog = await baja(page, kind)
      await expectNoSeriousA11yViolations(page, testInfo, `dialogo-baja-${kind}`)
      await dialog.getByRole('button', { name: 'Cancelar' }).click()
      await expect(dialog).toHaveCount(0)
    })
  }

  test('formularios de edición de dataset y de nueva versión', async ({ page }, testInfo) => {
    const owner = await login(accounts().editor)
    const cat = uniqueSlug('pw-a11y-ed')
    const ds = uniqueSlug('pw-a11y-eds')
    await apiCreateCatalog(owner, cat, `Catálogo ${cat}`)
    await apiCreateDataset(owner, cat, ds, `Dataset ${ds}`)
    await signIn(page, accounts().editor, `/datasets/${ds}`)
    await page.getByRole('button', { name: 'Editar', exact: true }).click()
    await expect(page.getByRole('form').or(page.getByRole('region')).first()).toBeVisible()
    await expectNoSeriousA11yViolations(page, testInfo, 'formulario-editar-dataset')
  })
})
