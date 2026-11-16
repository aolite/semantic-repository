import { expect, test } from '@playwright/test'
import { accounts, api, login } from '../support/api'
import { loginUi, watchConsole } from '../support/ui'

/**
 * Consola SPARQL: ejecuta una consulta de referencia sin sesión, muestra los errores de
 * validación y, con sesión, guarda una consulta personal que otro miembro no ve.
 */

test.describe.configure({ mode: 'serial' })

test('sin sesión: ejecuta una consulta de referencia y ve el resultado en tabla, JSON y CSV', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/sparql')
  await page.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: /Datasets clasificados en OT/ }).click()
  await expect(page.getByRole('textbox', { name: 'Consulta' })).toHaveValue(/SELECT/)
  // Sin sesión no hay «Guardar».
  await expect(page.getByRole('button', { name: 'Guardar', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Ejecutar' }).click()
  const results = page.getByRole('region', { name: 'Resultados' })
  await expect(results.getByRole('table')).toBeVisible()
  await expect(results.locator('.sparql__count')).toHaveText(/^[1-9]\d* resultados?$/)
  await expect(results.getByRole('table')).toContainText('modbus-tcp-testbed')

  await results.getByRole('button', { name: 'JSON' }).click()
  await expect(results).toContainText('"bindings"')
  await results.getByRole('button', { name: 'CSV' }).click()
  await expect(results.locator('pre, textarea').first()).toContainText(/\r?\n/)
  check()
})

test('los errores de validación se muestran con un mensaje claro', async ({ page }) => {
  await page.goto('/sparql')
  const editor = page.getByRole('textbox', { name: 'Consulta' })
  for (const query of ['DROP ALL', 'SELECT * { SERVICE <http://ejemplo.org/> { ?s ?p ?o } }', 'SELECT ?s WHERE { ?s ?p ']) {
    await editor.fill(query)
    await page.getByRole('button', { name: 'Ejecutar' }).click()
    const alert = page.getByRole('region', { name: 'Resultados' }).getByRole('alert')
    await expect(alert).toBeVisible()
    await expect(alert).not.toContainText(/Traceback|pyparsing|undefined/)
  }
  // La consulta vacía ni sale al servidor.
  await editor.fill('')
  await page.getByRole('button', { name: 'Ejecutar' }).click()
  await expect(page.getByRole('alert')).toContainText('Escribe una consulta')
})

test('un miembro guarda una consulta personal; otro miembro y el anónimo no la ven', async ({ page, browser }) => {
  const check = watchConsole(page)
  const { member, otherMember } = accounts()
  const title = `Mi consulta ${Date.now().toString(36)}`
  const query = 'SELECT ?s WHERE { ?s a <http://www.w3.org/ns/dcat#DatasetSeries> }'

  await loginUi(page, member)
  // La sesión vive en memoria: se navega dentro de la aplicación, sin recargar la página.
  await page.locator('nav').getByRole('link', { name: 'Consulta SPARQL' }).click()
  // Espera a que lleguen las consultas guardadas: antes, el editor aún no tiene selección.
  await expect(page.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: /Datasets clasificados en OT/ })).toBeVisible()
  await page.getByRole('textbox', { name: 'Consulta' }).fill(query)
  await page.getByRole('button', { name: 'Guardar', exact: true }).click()
  const form = page.getByRole('form', { name: 'Guardar consulta' })
  await form.getByLabel('Título').fill(title)
  await form.getByLabel('Pista (opcional)').fill('prueba de pantallas')
  await form.getByRole('button', { name: 'Guardar consulta' }).click()
  await expect(page.getByText('Consulta guardada.')).toBeVisible()
  const saved = page.getByRole('region', { name: 'Consultas guardadas' })
  await expect(saved.getByRole('button', { name: new RegExp(title) })).toBeVisible()

  // La consulta guardada se ejecuta.
  await page.getByRole('button', { name: 'Ejecutar' }).click()
  await expect(page.getByRole('region', { name: 'Resultados' }).getByRole('table')).toBeVisible()
  check()

  // Persiste: otra sesión del mismo miembro (contexto nuevo) la ve tras iniciar sesión.
  const again = await browser.newContext()
  const againPage = await again.newPage()
  await loginUi(againPage, member)
  await againPage.locator('nav').getByRole('link', { name: 'Consulta SPARQL' }).click()
  await expect(againPage.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: new RegExp(title) })).toBeVisible()
  await again.close()

  // Otro miembro (otro contexto de navegador) no la ve.
  const other = await browser.newContext()
  const otherPage = await other.newPage()
  await loginUi(otherPage, otherMember)
  await otherPage.locator('nav').getByRole('link', { name: 'Consulta SPARQL' }).click()
  const otherSaved = otherPage.getByRole('region', { name: 'Consultas guardadas' })
  await expect(otherSaved.getByRole('button', { name: /Datasets clasificados en OT/ })).toBeVisible()
  await expect(otherSaved.getByRole('button', { name: new RegExp(title) })).toHaveCount(0)
  await other.close()

  // El anónimo tampoco, y la API da 404 al intentar borrarla a otro usuario.
  const anonymous = await browser.newContext()
  const anonymousPage = await anonymous.newPage()
  await anonymousPage.goto('/sparql')
  await expect(anonymousPage.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: /Datasets clasificados en OT/ })).toBeVisible()
  await expect(anonymousPage.getByRole('button', { name: new RegExp(title) })).toHaveCount(0)
  await anonymous.close()

  // Limpieza: se borra por la API con la cuenta del dueño (la interfaz no borra).
  const token = await login(member)
  const mine = (await (await api('/sparql/queries', { token })).json()) as { id: string; title: string }[]
  const created = mine.find((q) => q.title === title)
  expect(created).toBeDefined()
  const foreign = await api(`/sparql/queries/${created!.id}`, { method: 'DELETE', token: await login(otherMember) })
  expect(foreign.status).toBe(404)
  const removed = await api(`/sparql/queries/${created!.id}`, { method: 'DELETE', token })
  expect(removed.status).toBe(204)
})

// QA-G4-04 (frontend): lo que se escribe en el editor antes de que lleguen las consultas
// guardadas se pierde, porque al llegar se carga el texto de la primera de referencia. Se
// reproduce de forma determinista retrasando la respuesta de `/sparql/queries`.
test.fail('QA-G4-04: el texto escrito antes de que carguen las consultas guardadas se conserva', async ({ page }) => {
  await page.route('**/sparql/queries', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.goto('/sparql')
  const editor = page.getByRole('textbox', { name: 'Consulta' })
  const mine = 'ASK { ?s ?p ?o } # escrito por la persona usuaria'
  await editor.fill(mine)
  await expect(page.getByRole('region', { name: 'Consultas guardadas' }).getByRole('button', { name: /Datasets clasificados en OT/ })).toBeVisible()
  await expect(editor).toHaveValue(mine)
})
