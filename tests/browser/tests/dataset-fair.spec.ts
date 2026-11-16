import { expect, test } from '@playwright/test'
import { accounts, api, login, publishSeries, seriesTurtle, uploadFile } from '../support/api'
import { loginUi, MODBUS, MODBUS_TITLE, syntheticFile, watchConsole } from '../support/ui'

/**
 * Ficha de dataset en G4: evaluación FAIR real de F-UJI y descargas según `download`
 * (decisión 40): «Descargar», «Iniciar sesión para descargar» y solo metadatos.
 */

interface Fair {
  status: string
  total: number
  findable: number
  accessible: number
  interoperable: number
  reusable: number
  maturity: string
  evaluator: string
  evaluated_at: string
  report_url: string
}

test('la sección FAIR muestra la evaluación real de F-UJI y enlaza el informe completo', async ({ page, request }) => {
  const check = watchConsole(page)
  const detail = (await (await api(`/datasets/${MODBUS}`)).json()) as { version: { fair: Fair } }
  const fair = detail.version.fair
  expect(fair.status).toBe('done')

  await page.goto(`/datasets/${MODBUS}`)
  const section = page.locator('section.fair')
  await expect(section.getByRole('heading', { level: 2, name: 'Evaluación FAIR' })).toBeVisible()
  await expect(section.locator('.fair__total')).toHaveText(String(fair.total))
  await expect(section.locator('.fair__maturity')).toHaveText(`Madurez ${fair.maturity} / 3`)
  const scores: [string, number][] = [
    ['F · Findable', fair.findable],
    ['A · Accessible', fair.accessible],
    ['I · Interoperable', fair.interoperable],
    ['R · Reusable', fair.reusable],
  ]
  for (const [label, score] of scores) {
    await expect(section.locator('.fair__dim', { hasText: label }).locator('.fair__dim-score')).toHaveText(String(score))
  }
  await expect(section).toContainText('Última evaluación:')
  await expect(section).toContainText(`Evaluador: ${fair.evaluator}`)
  await expect(section).not.toContainText('[MOTOR FAIR]')

  const link = section.getByRole('link', { name: 'Ver informe completo de pruebas' })
  await expect(link).toBeVisible()
  const href = await link.getAttribute('href')
  expect(href).toContain(`/datasets/${MODBUS}/versions/2.1.0/fair/report`)
  const report = await request.get(href!)
  expect(report.ok()).toBe(true)
  const body = (await report.json()) as { summary: { score_percent: { FAIR: number } }; software_version: string }
  expect(body.summary.score_percent.FAIR).toBe(fair.total)
  expect(fair.evaluator).toContain(body.software_version)
  check()
})

test('sin sesión: «Iniciar sesión para descargar» en las restringidas y sin botón «Descargar»', async ({ page }) => {
  await page.goto(`/datasets/${MODBUS}`)
  const table = page.locator('#distribuciones')
  await expect(table.getByRole('link', { name: /^Iniciar sesión para descargar/ })).toHaveCount(3) // csv, pcap y parquet
  await expect(table.getByRole('link', { name: /^Descargar/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Solicitar acceso|Nueva versión/ })).toHaveCount(0)
})

test('un miembro inicia sesión desde la ficha, vuelve a ella y descarga con enlace firmado', async ({ page }) => {
  const check = watchConsole(page)
  const { member } = accounts()
  await page.goto(`/datasets/${MODBUS}?version=2.1.0`)
  await page.locator('#distribuciones').getByRole('link', { name: /^Iniciar sesión para descargar/ }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await loginUi(page, member, 'ya-en-login')
  // Vuelve a la misma ficha y versión.
  await expect(page).toHaveURL(new RegExp(`/datasets/${MODBUS}\\?version=2\\.1\\.0$`))
  const table = page.locator('#distribuciones')
  await expect(table.getByRole('link', { name: /^Iniciar sesión para descargar/ })).toHaveCount(0)
  const buttons = table.getByRole('button', { name: /^Descargar/ })
  await expect(buttons).toHaveCount(3)

  const row = table.locator('tr', { hasText: 'csv' }).first()
  const [download] = await Promise.all([page.waitForEvent('download'), row.getByRole('button', { name: /^Descargar/ }).click()])
  expect(download.suggestedFilename()).toBe(`${MODBUS}-2.1.0-csv.csv`)
  const stream = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(chunk as Buffer)
  expect(Buffer.concat(chunks).equals(syntheticFile(MODBUS, '2.1.0', 'csv.csv'))).toBe(true)
  check()
})

test('distribuciones PUBLIC, RESTRICTED y NON_PUBLIC de una serie nueva en la ficha', async ({ page }) => {
  const { editor } = accounts()
  const token = await login(editor)
  const slug = `browser-acc-${Date.now().toString(36)}`
  const turtle = seriesTurtle(slug, `Serie de accesos ${slug}`, {
    '1.0.0': { access: 'RESTRICTED', dists: { abierta: 'PUBLIC', restringida: null, defensa: 'NON_PUBLIC', pendiente: 'RESTRICTED' } },
  })
  await publishSeries(token, turtle)
  expect(await uploadFile(token, slug, '1.0.0', 'abierta', new TextEncoder().encode('a,b\n1,2\n'))).toBe(201)
  expect(await uploadFile(token, slug, '1.0.0', 'restringida', new TextEncoder().encode('c,d\n3,4\n'))).toBe(201)
  expect(await uploadFile(token, slug, '1.0.0', 'defensa', new TextEncoder().encode('x'))).toBe(409)

  await page.goto(`/datasets/${slug}`)
  const table = page.locator('#distribuciones')
  // PUBLIC: cualquiera descarga, sin sesión.
  const open = table.locator('tr', { hasText: 'abierta' })
  await expect(open.getByRole('link', { name: /^Descargar/ })).toBeVisible()
  const [download] = await Promise.all([page.waitForEvent('download'), open.getByRole('link', { name: /^Descargar/ }).click()])
  expect(download.suggestedFilename()).toBe(`${slug}-1.0.0-abierta.csv`)
  // RESTRICTED sin sesión: pide iniciar sesión.
  await expect(table.locator('tr', { hasText: 'restringida' }).getByRole('link', { name: /^Iniciar sesión para descargar/ })).toBeVisible()
  // NON_PUBLIC: solo metadatos, nunca una acción de descarga.
  const defensa = table.locator('tr', { hasText: 'defensa' })
  await expect(defensa).toContainText('Solo metadatos')
  await expect(defensa.getByRole('link')).toHaveCount(0)
  await expect(defensa.getByRole('button')).toHaveCount(0)
  // Sin fichero subido: «No disponible», sin acción de descarga.
  const pendiente = table.locator('tr', { hasText: 'pendiente' })
  await expect(pendiente).toContainText('No disponible')
  await expect(pendiente.getByRole('link')).toHaveCount(0)
  await expect(pendiente.getByRole('button')).toHaveCount(0)
})
