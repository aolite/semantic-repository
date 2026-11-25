/**
 * Cliente mínimo de la API para preparar y comprobar datos desde las pruebas.
 * Solo habla con API_URL (el backend del entorno de pruebas).
 */
export const API_URL = (process.env.API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export const AR = 'http://publications.europa.eu/resource/authority/access-right/'
const IANA = 'http://www.iana.org/assignments/media-types/'

export interface Account {
  username: string
  password: string
  role: 'miembro' | 'editor' | 'admin'
}

export interface Accounts {
  admin: Account
  member: Account
  otherMember: Account
  editor: Account
}

export function accounts(): Accounts {
  const raw = process.env.QA_BROWSER_ACCOUNTS
  if (!raw) throw new Error('Faltan las cuentas de la prueba: no se ha ejecutado global-setup')
  return JSON.parse(raw) as Accounts
}

export async function api(path: string, init: RequestInit & { token?: string } = {}): Promise<Response> {
  const { token, ...rest } = init
  const headers = new Headers(rest.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${API_URL}${path}`, { ...rest, headers })
}

export async function login(account: Account): Promise<string> {
  const response = await api('/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: account.username, password: account.password }),
  })
  if (!response.ok) throw new Error(`login de ${account.role} falló: ${response.status}`)
  return ((await response.json()) as { access_token: string }).access_token
}

export interface SeriesVersion {
  access: 'PUBLIC' | 'RESTRICTED' | 'NON_PUBLIC'
  dists: Record<string, 'PUBLIC' | 'RESTRICTED' | 'NON_PUBLIC' | null>
}

/** Serie mínima válida (Turtle con IRIs relativas a BASE_URI), marcada como sintética. */
export function seriesTurtle(slug: string, title: string, versions: Record<string, SeriesVersion>): string {
  const names = Object.keys(versions)
  const last = names[names.length - 1]
  const out = [
    '@prefix dcat: <http://www.w3.org/ns/dcat#> .',
    '@prefix dct:  <http://purl.org/dc/terms/> .',
    `<dataset/${slug}> a dcat:DatasetSeries ; dct:type <vocab/tipo-dataset/sintetico> ;`,
    `    dct:title "${title}"@es ; dct:description "Serie de la prueba de pantallas."@es ;`,
    `    dcat:last <dataset/${slug}/${last}> .`,
  ]
  let previous: string | null = null
  for (const [version, spec] of Object.entries(versions)) {
    const links = Object.keys(spec.dists).map((d) => `<dataset/${slug}/${version}/${d}>`).join(', ')
    out.push(
      `<dataset/${slug}/${version}> a dcat:Dataset ; dct:type <vocab/tipo-dataset/sintetico> ;`,
      `    dct:title "${title}"@es ; dct:description "Serie de la prueba de pantallas."@es ;`,
      `    dcat:version "${version}" ; dcat:inSeries <dataset/${slug}> ;`,
      `    dct:accessRights <${AR}${spec.access}> ; dcat:theme <vocab/ot/modbus-tcp> ;`,
    )
    if (previous) out.push(`    dcat:previousVersion <dataset/${slug}/${previous}> ;`)
    out.push(`    dcat:distribution ${links} .`)
    for (const [dist, access] of Object.entries(spec.dists)) {
      out.push(
        `<dataset/${slug}/${version}/${dist}> a dcat:Distribution ; ${access ? `dct:accessRights <${AR}${access}> ;` : ''}`,
        `    dcat:mediaType <${IANA}text/csv> ; dcat:accessURL <dataset/${slug}/${version}/${dist}> .`,
      )
    }
    previous = version
  }
  return out.join('\n') + '\n'
}

/** Catálogo de las series que publican las pruebas (decisión 49: cada serie está en uno). */
export const BROWSER_CATALOG = 'browser-pruebas'

/** Crea el catálogo de las pruebas. Idempotente: si ya existe (409), no hace nada. */
export async function ensureCatalog(token: string, slug: string = BROWSER_CATALOG): Promise<void> {
  const response = await api('/catalogs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      slug,
      title: 'Catálogo de las pruebas de pantallas',
      description: 'Catálogo ficticio creado por las pruebas de Playwright.',
      publisher_name: 'Pruebas de QA',
    }),
    token,
  })
  if (![201, 409].includes(response.status)) {
    throw new Error(`crear el catálogo falló: ${response.status} ${(await response.text()).slice(0, 300)}`)
  }
}

export async function publishSeries(
  token: string,
  turtle: string,
  catalog: string = BROWSER_CATALOG,
): Promise<number> {
  const response = await api(`/datasets?catalog=${encodeURIComponent(catalog)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/turtle' },
    body: turtle,
    token,
  })
  if (![200, 201].includes(response.status)) {
    throw new Error(`publicar falló: ${response.status} ${(await response.text()).slice(0, 300)}`)
  }
  return response.status
}

/** Un slug nuevo y único para los recursos que crea una prueba. */
export function uniqueSlug(prefix: string): string {
  return `${prefix}-${Math.random().toString(16).slice(2, 8)}`
}

async function jsonCall(method: string, path: string, token: string, body?: unknown): Promise<Response> {
  return api(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    token,
  })
}

/** Crea un catálogo por la API (datos ficticios). Falla si no es 201. */
export async function apiCreateCatalog(token: string, slug: string, title = `Catálogo ${slug}`): Promise<void> {
  const response = await jsonCall('POST', '/catalogs', token, {
    slug,
    title,
    description: 'Catálogo ficticio de las pruebas de pantallas.',
    publisher_name: 'Pruebas de QA',
  })
  if (response.status !== 201) throw new Error(`crear catálogo ${slug}: ${response.status}`)
}

/** Crea un dataset (serie sin versiones) en un catálogo por la API. */
export async function apiCreateDataset(
  token: string,
  catalog: string,
  slug: string,
  title = `Dataset ${slug}`,
  publisherName?: string,
): Promise<void> {
  const response = await jsonCall('POST', `/catalogs/${catalog}/datasets`, token, {
    slug,
    title,
    description: 'Dataset ficticio de las pruebas de pantallas.',
    ...(publisherName ? { publisher_name: publisherName } : {}),
  })
  if (response.status !== 201) throw new Error(`crear dataset ${slug}: ${response.status}`)
}

export async function apiWithdraw(token: string, kind: 'catalogs' | 'datasets', slug: string): Promise<void> {
  const response = await jsonCall('DELETE', `/${kind}/${slug}`, token)
  if (response.status !== 204) throw new Error(`dar de baja ${slug}: ${response.status}`)
}

export async function apiMoveDataset(token: string, slug: string, catalog: string): Promise<void> {
  const response = await jsonCall('PATCH', `/datasets/${slug}`, token, { catalog })
  if (response.status !== 200) throw new Error(`mover ${slug}: ${response.status}`)
}

export async function uploadFile(
  token: string,
  slug: string,
  version: string,
  dist: string,
  data: Uint8Array,
): Promise<number> {
  const form = new FormData()
  form.append('file', new Blob([data as BlobPart], { type: 'application/octet-stream' }), 'x.bin')
  const response = await api(`/datasets/${slug}/versions/${version}/distributions/${dist}/file`, {
    method: 'PUT',
    body: form,
    token,
  })
  return response.status
}
