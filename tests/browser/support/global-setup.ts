import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { api, login, publishSeries, seriesTurtle, type Account, type Accounts } from './api'

/**
 * Prepara el entorno de las pruebas, sin datos ni credenciales fijas:
 * 1. Crea un admin con la CLI del backend (`docker compose exec`), salvo que se den
 *    BROWSER_ADMIN_USER y BROWSER_ADMIN_PASSWORD.
 * 2. Con el admin, crea un editor y dos miembros con contraseñas aleatorias. Las cuentas
 *    viajan a los workers en una variable de entorno, nunca a un fichero.
 * 3. Publica las series que necesita la paginación y espera a que F-UJI termine la
 *    evaluación de los datasets sintéticos (`load-semantic` ya se ha ejecutado).
 */
const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = join(here, '..', '..', '..')

export const PAGINATION_SERIES = 21
export const PAGINATION_PREFIX = 'Serie de paginación'

function secret(): string {
  return randomBytes(18).toString('base64url')
}

function composeArgs(): string[] {
  const extra = (process.env.BROWSER_COMPOSE_ARGS ?? '').split(/\s+/).filter(Boolean)
  return ['compose', ...extra, '--project-directory', repoRoot, '--file', join(repoRoot, 'docker-compose.yml')]
}

function createAdmin(): Account {
  const given = process.env.BROWSER_ADMIN_USER
  if (given && process.env.BROWSER_ADMIN_PASSWORD) {
    return { username: given, password: process.env.BROWSER_ADMIN_PASSWORD, role: 'admin' }
  }
  const account: Account = { username: `browser-admin-${randomBytes(3).toString('hex')}`, password: secret(), role: 'admin' }
  try {
    execFileSync(
      'docker',
      [...composeArgs(), 'exec', '-T', 'backend', 'python', '-m', 'app.cli', 'create-admin', '--username', account.username, '--password-stdin'],
      { input: `${account.password}\n`, stdio: ['pipe', 'pipe', 'pipe'], timeout: 120_000 },
    )
  } catch (error) {
    const stderr = (error as { stderr?: Buffer }).stderr?.toString() ?? ''
    // Nunca se imprime la contraseña: solo el motivo que da docker.
    throw new Error(`No se ha podido crear el admin con la CLI del backend: ${stderr.slice(0, 400)}`)
  }
  return account
}

async function createUser(adminToken: string, role: 'miembro' | 'editor'): Promise<Account> {
  const account: Account = { username: `browser-${role}-${randomBytes(3).toString('hex')}`, password: secret(), role }
  const response = await api('/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(account),
    token: adminToken,
  })
  if (response.status !== 201) throw new Error(`no se pudo crear ${role}: ${response.status}`)
  return account
}

async function waitFor<T>(what: string, timeoutMs: number, probe: () => Promise<T | null>): Promise<T> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const value = await probe().catch(() => null)
    if (value !== null) return value
    if (Date.now() > deadline) throw new Error(`Tiempo agotado esperando: ${what}`)
    await new Promise((resolve) => setTimeout(resolve, 3000))
  }
}

export default async function globalSetup(): Promise<void> {
  await waitFor('el backend listo', 120_000, async () => ((await api('/health/ready')).ok ? true : null))
  const listed = await waitFor('los datasets sintéticos (¿load-semantic?)', 120_000, async () => {
    const body = (await (await api('/datasets?page_size=100')).json()) as { items: { slug: string }[] }
    return body.items.some((d) => d.slug === 'modbus-tcp-testbed') ? body : null
  })
  if (listed.items.length < 3) throw new Error('Faltan los datasets sintéticos: ejecuta load-semantic antes')

  const admin = createAdmin()
  const adminToken = await login(admin)
  const accountsValue: Accounts = {
    admin,
    editor: await createUser(adminToken, 'editor'),
    member: await createUser(adminToken, 'miembro'),
    otherMember: await createUser(adminToken, 'miembro'),
  }
  process.env.QA_BROWSER_ACCOUNTS = JSON.stringify(accountsValue)

  // Series para la paginación (20 por página): idempotente, republicar lo mismo no cambia nada.
  const editorToken = await login(accountsValue.editor)
  for (let n = 1; n <= PAGINATION_SERIES; n += 1) {
    const slug = `browser-pag-${String(n).padStart(2, '0')}`
    await publishSeries(
      editorToken,
      seriesTurtle(slug, `${PAGINATION_PREFIX} ${String(n).padStart(2, '0')}`, {
        '1.0.0': { access: 'PUBLIC', dists: { csv: 'PUBLIC' } },
      }),
    )
  }

  // F-UJI real: la ficha de los sintéticos muestra la evaluación cuando termina.
  await waitFor('la evaluación FAIR de modbus-tcp-testbed (F-UJI)', 600_000, async () => {
    const body = (await (await api('/datasets/modbus-tcp-testbed')).json()) as {
      version: { fair: { status: string } | null }
    }
    return body.version.fair?.status === 'done' ? true : null
  })
}
