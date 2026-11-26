import { expect, test } from '@playwright/test'
import { api } from '../support/api'
import { expectNoBrokenText, MODBUS, MODBUS_TITLE, syntheticTitle, watchConsole } from '../support/ui'

/**
 * Las 6 pantallas del prototipo cargan con contenido real del backend (datos sintéticos de
 * `load-semantic`), sin errores de consola y sin textos rotos.
 */

test('Catálogo: lista los datasets sintéticos y los vocabularios con datos reales', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Datasets y vocabularios controlados' })).toBeVisible()
  const cards = page.getByRole('list', { name: 'Recursos' })
  await expect(cards.locator('article.card').first()).toBeVisible()
  await expect(page.locator('.section-bar__count')).toHaveText(/^\d+ recursos$/)
  // Cada dataset sintético se encuentra por su slug (la búsqueda mira también la URI).
  for (const slug of ['modbus-tcp-testbed', 'hallazgos-auditorias-intrusion', 'ejemplos-adversarios-vision']) {
    await page.goto(`/?q=${slug}&tipo=datasets`)
    await expect(cards.locator('article.card')).toHaveCount(1)
    await expect(cards.getByRole('link', { name: syntheticTitle(slug) })).toBeVisible()
    await expect(cards).toContainText('dcat:Dataset')
    await expect(cards).toContainText('Dataset sintético')
  }
  // «FAIR n» de la tarjeta es el total real de la última evaluación de F-UJI.
  await page.goto(`/?q=${MODBUS}&tipo=datasets`)
  const detail = (await (await api(`/datasets/${MODBUS}`)).json()) as { version: { fair: { total: number } } }
  await expect(page.locator('article.card', { hasText: MODBUS_TITLE }).locator('.card__fair-label')).toHaveText(
    `FAIR ${detail.version.fair.total}`,
  )
  await page.goto('/?tipo=vocabularios')
  await expect(cards).toContainText('owl:Ontology')
  await expect(cards).toContainText('skos:ConceptScheme')
  await expect(cards).toContainText('Ontología de activos y amenazas IT/OT')
  await expectNoBrokenText(page)
  check()
})

test('Ficha de dataset: versión actual, historial, distribuciones y procedencia', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto(`/datasets/${MODBUS}`)
  await expect(page.getByRole('heading', { level: 1, name: MODBUS_TITLE })).toBeVisible()
  for (const heading of ['Descripción', 'Versionado', 'Distribuciones', 'Procedencia', 'Evaluación FAIR', 'Metadatos DCAT-AP']) {
    await expect(page.getByRole('heading', { level: 2, name: heading, exact: true })).toBeVisible()
  }
  await expect(page.getByText('v2.1.0 · actual')).toBeVisible()
  const history = page.locator('.history__list')
  for (const version of ['2.1.0', '2.0.0', '1.0.0']) {
    await expect(history.getByRole('link', { name: `Versión ${version}` })).toBeVisible()
  }
  // Una versión antigua tiene su propia ficha.
  await history.getByRole('link', { name: 'Versión 1.0.0' }).click()
  await expect(page).toHaveURL(/version=1\.0\.0/)
  await expect(page.locator('header').getByText('v1.0.0')).toBeVisible()
  await expect(page.locator('header').getByText('actual')).toHaveCount(0)
  await expectNoBrokenText(page)
  check()
})

test('Vocabularios y ontologías: recuentos y filtros por tipo', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/vocabularios')
  await expect(page.getByRole('heading', { level: 1, name: 'Vocabularios y ontologías' })).toBeVisible()
  for (const label of ['Ontologías propias', 'Ontologías externas', 'SKOS corporativos', 'SKOS de dominio']) {
    await expect(page.locator('main').getByText(label).first()).toBeVisible()
  }
  await expect(page.getByText(/^\d+ vocabularios$/)).toBeVisible()
  await page.getByRole('group', { name: 'Tipo de vocabulario' }).getByRole('button', { name: 'Ontologías propias' }).click()
  // Los tres de los datos sintéticos, y los que hayan publicado otras pruebas (decisión 50): no se
  // fija el total, que depende del orden de los ficheros.
  await expect
    .poll(async () => Number((await page.getByText(/^\d+ vocabularios$/).innerText()).match(/\d+/)?.[0] ?? 0))
    .toBeGreaterThanOrEqual(3)
  await expect(page.getByText('Ontología de activos y amenazas IT/OT')).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('Ficha de ontología: itot con métricas, versionado y uso en el catálogo', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/ontologias/itot')
  await expect(page.getByRole('heading', { level: 1, name: 'Ontología de activos y amenazas IT/OT' })).toBeVisible()
  for (const heading of ['Descripción', 'Métricas', 'Imports y alineamientos', 'Versionado', 'Uso en el catálogo', 'Metadatos']) {
    await expect(page.getByRole('heading', { level: 2, name: heading, exact: true })).toBeVisible()
  }
  await expect(page.getByText('v1.2.0 · actual')).toBeVisible()
  await expect(page.locator('main')).toContainText('13')
  await expect(page.getByRole('link', { name: 'Descargar Turtle' })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('Navegador SKOS: jerarquía del esquema ot, filtro y detalle de un concepto', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/vocabularios/ot')
  await expect(page.getByRole('heading', { level: 1, name: 'Protocolos y arquitectura OT' })).toBeVisible()
  await expect(page.getByText('16 conceptos')).toBeVisible()
  await page.getByLabel('Filtrar conceptos').fill('modbus')
  await expect(page.getByText(/^\d+ conceptos?$/).first()).toBeVisible()
  const tree = page.getByRole('tree')
  await expect(tree.getByRole('treeitem', { name: 'Modbus/TCP' })).toBeVisible()
  await tree.getByRole('treeitem', { name: 'Modbus/TCP' }).click()
  await expect(page.getByRole('heading', { level: 3, name: 'Recursos que usan este concepto' })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})

test('Consola SPARQL: consultas de referencia, editor y endpoint', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/sparql')
  await expect(page.getByRole('heading', { level: 1, name: 'Consulta SPARQL' })).toBeVisible()
  await expect(page.locator('.sparql__endpoint')).toContainText('/sparql')
  const saved = page.getByRole('region', { name: 'Consultas guardadas' })
  for (const title of ['Mapeos a vocabularios externos', 'Datasets clasificados en OT', 'Conceptos sin definición']) {
    await expect(saved.getByRole('button', { name: new RegExp(title) })).toBeVisible()
  }
  await expect(page.getByRole('textbox', { name: 'Consulta' })).not.toHaveValue('')
  await expect(page.getByRole('button', { name: 'Ejecutar' })).toBeVisible()
  await expectNoBrokenText(page)
  check()
})
