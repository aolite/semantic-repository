import { expect, test } from '@playwright/test'
import { MODBUS_TITLE, syntheticTitle, watchConsole } from '../support/ui'

/**
 * Catálogo (decisión 33): paginación y filtros en la URL. Las 21 «series de paginación» las
 * publica `support/global-setup.ts`, así que `q=paginación` da dos páginas (20 + 1).
 */

const cards = (page: import('@playwright/test').Page) => page.getByRole('list', { name: 'Recursos' }).locator('article.card')

test('paginación: 20 por página, la página va en la URL y se puede abrir directamente', async ({ page }) => {
  const check = watchConsole(page)
  await page.goto('/?q=paginación&tipo=datasets')
  await expect(page.locator('.section-bar__count')).toHaveText('21 recursos')
  await expect(cards(page)).toHaveCount(20)
  const pager = page.getByRole('navigation', { name: 'Paginación' })
  await expect(pager).toContainText('Página 1 de 2')
  await expect(pager.getByRole('link', { name: 'Anterior' })).toHaveCount(0)

  await pager.getByRole('link', { name: 'Siguiente' }).click()
  await expect(page).toHaveURL(/pagina=2/)
  await expect(page).toHaveURL(/q=paginaci/)
  await expect(pager).toContainText('Página 2 de 2')
  await expect(cards(page)).toHaveCount(1)
  await expect(pager.getByRole('link', { name: 'Siguiente' })).toHaveCount(0)

  // Atrás vuelve a la primera página; abrir la URL de la segunda la carga directamente.
  await page.goBack()
  await expect(pager).toContainText('Página 1 de 2')
  await page.goto('/?q=paginación&tipo=datasets&pagina=2')
  await expect(pager).toContainText('Página 2 de 2')
  await expect(cards(page)).toHaveCount(1)
  await pager.getByRole('link', { name: 'Anterior' }).click()
  await expect(cards(page)).toHaveCount(20)
  check()
})

test('los filtros de dominio y tipo, y la búsqueda, quedan en la URL y se restauran al recargar', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('group', { name: 'Dominio' }).getByRole('button', { name: 'IA adversaria' }).click()
  await expect(page).toHaveURL(/dominio=ia/)
  await expect(cards(page).filter({ hasText: syntheticTitle('ejemplos-adversarios-vision') })).toHaveCount(1)
  await expect(cards(page).filter({ hasText: MODBUS_TITLE })).toHaveCount(0)

  await page.getByRole('group', { name: 'Tipo de recurso' }).getByRole('button', { name: 'Datasets' }).click()
  await expect(page).toHaveURL(/tipo=datasets/)
  await expect(page).toHaveURL(/dominio=ia/)
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page).first()).toContainText('dcat:Dataset')

  await page.getByRole('group', { name: 'Dominio' }).getByRole('button', { name: 'Todos los dominios' }).click()
  await expect(page).not.toHaveURL(/dominio=/)
  // Espera a que la pantalla refleje el filtro antes de escribir en el buscador.
  await expect(page.getByRole('group', { name: 'Dominio' }).getByRole('button', { name: 'Todos los dominios' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('Buscar en el catálogo').fill('Tráfico')
  await expect(page).toHaveURL(/q=Tr%C3%A1fico|q=Tráfico/)
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page).first()).toContainText(MODBUS_TITLE)

  // Recargar conserva el estado: el campo, los chips y los resultados.
  await page.reload()
  await expect(page.getByLabel('Buscar en el catálogo')).toHaveValue('Tráfico')
  await expect(page.getByRole('group', { name: 'Tipo de recurso' }).getByRole('button', { name: 'Datasets' })).toHaveAttribute('aria-pressed', 'true')
  await expect(cards(page)).toHaveCount(1)

  // El botón atrás deshace el último filtro («Todos los dominios»); la búsqueda no crea
  // entradas de historial porque sustituye la actual.
  await page.goBack()
  await expect(page).toHaveURL(/dominio=ia/)
  await expect(page.getByRole('group', { name: 'Dominio' }).getByRole('button', { name: 'IA adversaria' })).toHaveAttribute('aria-pressed', 'true')
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page).first()).toContainText(syntheticTitle('ejemplos-adversarios-vision'))
})

test('filtro «Vocabularios y ontologías» y una búsqueda sin resultados', async ({ page }) => {
  await page.goto('/?tipo=vocabularios')
  await expect(page.getByRole('group', { name: 'Tipo de recurso' }).getByRole('button', { name: 'Vocabularios y ontologías' })).toHaveAttribute('aria-pressed', 'true')
  await expect(cards(page).first()).toBeVisible()
  await expect(page.getByRole('list', { name: 'Recursos' })).not.toContainText('dcat:Dataset')
  await page.goto('/?q=zzz-no-existe-zzz')
  await expect(page.getByText('Ningún recurso coincide con los filtros.')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Paginación' })).toHaveCount(0)
})
