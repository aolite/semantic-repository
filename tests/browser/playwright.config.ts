import { defineConfig, devices } from '@playwright/test'

/**
 * Pruebas de pantallas (decisión 34) sobre el Compose real, con Chromium.
 *
 * Variables (las del job `browser` de .github/workflows/ci.yml):
 * - BASE_URL: el frontend (por defecto http://localhost:5173).
 * - API_URL: el backend (por defecto http://localhost:8000).
 * - CI: con `true`, un reintento y informe HTML.
 * - BROWSER_COMPOSE_ARGS: opciones extra de `docker compose` para crear las cuentas de
 *   la prueba con la CLI del backend (p. ej. `-p miproyecto`).
 * - BROWSER_ADMIN_USER y BROWSER_ADMIN_PASSWORD: un admin ya existente, en lugar de crearlo.
 *
 * Un solo worker: las pruebas comparten backend y el SPARQL anónimo tiene límite por IP.
 */
const ci = Boolean(process.env.CI)

export default defineConfig({
  testDir: './tests',
  globalSetup: './support/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: ci ? [['list'], ['html', { open: 'never' }]] : [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:5173',
    locale: 'es-ES',
    trace: ci ? 'on-first-retry' : 'retain-on-failure',
    screenshot: 'only-on-failure',
    acceptDownloads: true,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
