import { expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Account } from './api'

const here = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = join(here, '..', '..', '..')

export const MODBUS = 'modbus-tcp-testbed'
export const MODBUS_TITLE = 'Tráfico Modbus/TCP del banco de pruebas OT'

/** Título (`dct:title`, español) de una serie sintética, leído de `semantic/data/sintetico/`. */
export function syntheticTitle(slug: string): string {
  const text = readFileSync(join(REPO_ROOT, 'semantic', 'data', 'sintetico', `${slug}.ttl`), 'utf-8')
  const match = text.match(/^\s*dct:title "([^"]+)"@es/m)
  if (!match) throw new Error(`sin título en ${slug}`)
  return match[1]
}

/** Contenido de un fichero sintético de distribución (`semantic/data/sintetico/ficheros/`). */
export function syntheticFile(slug: string, version: string, name: string): Buffer {
  return readFileSync(join(REPO_ROOT, 'semantic', 'data', 'sintetico', 'ficheros', slug, version, name))
}

/** Falla la prueba si la página escribe errores en la consola o lanza excepciones. */
export function watchConsole(page: Page): () => void {
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(`excepción: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`consola: ${message.text()}`)
  })
  return () => expect(problems, 'errores de consola o excepciones').toEqual([])
}

/** Inicia sesión por la interfaz y espera a ver el nombre de usuario en la barra lateral. */
export async function loginUi(page: Page, account: Account, from = '/login'): Promise<void> {
  if (from !== 'ya-en-login') await page.goto(from)
  await page.getByLabel('Usuario').fill(account.username)
  await page.getByLabel('Contraseña').fill(account.password)
  await page.locator('main').getByRole('button', { name: 'Iniciar sesión' }).click()
  await expect(page.locator('.sidebar__username')).toHaveText(account.username)
}

/** El texto de la página no debe llevar restos de un render roto. */
export async function expectNoBrokenText(page: Page): Promise<void> {
  const text = await page.locator('main').innerText()
  expect(text, 'restos de un render roto').not.toMatch(/\b(undefined|null|NaN)\b|\[object Object\]/)
}
