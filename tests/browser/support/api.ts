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


// --- Esquemas SKOS y ontologías en los catálogos (decisión 50) ---------------------------

/** Prefijo VANN válido (minúsculas y dígitos) derivado de un slug. */
export function defaultPrefix(slug: string): string {
  return `p${slug.replace(/[^a-z0-9]/g, '')}`
}

export function uniquePrefix(prefix: string): string {
  return defaultPrefix(uniqueSlug(prefix))
}

export interface SchemeOptions {
  corp?: boolean
  concepts?: string[]
  /** `{concepto: [sustitutos]}` */
  deprecated?: Record<string, string[]>
  prefix?: string
  title?: string
}

/** Esquema SKOS mínimo ficticio (Turtle con IRIs relativas a BASE_URI): la raíz es `concepts[0]`. */
export function schemeTurtle(slug: string, options: SchemeOptions = {}): string {
  const { corp = false, concepts = ['raiz', 'hoja'], deprecated = {}, prefix = defaultPrefix(slug), title = `Esquema ${slug}` } = options
  const path = corp ? `vocab/corp/${slug}` : `vocab/${slug}`
  const [root, ...leaves] = concepts
  const out = [
    '@prefix skos: <http://www.w3.org/2004/02/skos/core#> .',
    '@prefix dct: <http://purl.org/dc/terms/> .',
    '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
    '@prefix adms: <http://www.w3.org/ns/adms#> .',
    '@prefix vann: <http://purl.org/vocab/vann/> .',
    `<${path}> a skos:ConceptScheme ; ${corp ? '' : 'dct:subject <vocab/dominio/it> ;'}`,
    '    dct:type <vocab/tipo-dataset/sintetico> ;',
    `    skos:prefLabel "${title}"@es ; dct:title "${title}"@es ;`,
    '    dct:description "Esquema ficticio de las pruebas de pantallas."@es ;',
    '    owl:versionInfo "1.0" ; adms:status <http://purl.org/adms/status/Completed> ;',
    `    vann:preferredNamespacePrefix "${prefix}" ; vann:preferredNamespaceUri <${path}/> ;`,
    `    skos:hasTopConcept <${path}/${root}> .`,
    `<${path}/${root}> a skos:Concept ; skos:inScheme <${path}> ; skos:topConceptOf <${path}> ; skos:prefLabel "Raíz"@es .`,
  ]
  for (const leaf of leaves) {
    out.push(`<${path}/${leaf}> a skos:Concept ; skos:inScheme <${path}> ; skos:broader <${path}/${root}> ; skos:prefLabel "Hoja ${leaf}"@es .`)
  }
  for (const [concept, targets] of Object.entries(deprecated)) {
    out.push(`<${path}/${concept}> owl:deprecated "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .`)
    for (const target of targets) out.push(`<${path}/${concept}> dct:isReplacedBy <${target}> .`)
  }
  return out.join('\n') + '\n'
}

export function ontologyTurtle(slug: string, options: { prefix?: string; version?: string; prior?: string; extra?: string } = {}): string {
  const { prefix = defaultPrefix(slug), version = '1.0.0', prior, extra = '' } = options
  return [
    '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
    '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .',
    '@prefix dct: <http://purl.org/dc/terms/> .',
    '@prefix adms: <http://www.w3.org/ns/adms#> .',
    '@prefix vann: <http://purl.org/vocab/vann/> .',
    `@prefix : <onto/${slug}#> .`,
    `<onto/${slug}> a owl:Ontology ; owl:versionIRI <onto/${slug}/${version}> ; owl:versionInfo "${version}" ;`,
    prior ? `    owl:priorVersion <onto/${slug}/${prior}> ;` : '',
    '    dct:type <vocab/tipo-dataset/sintetico> ; adms:status <http://purl.org/adms/status/UnderDevelopment> ;',
    `    dct:title "Ontología ${slug}"@es ; dct:description "Ontología ficticia de las pruebas de pantallas."@es ;`,
    `    vann:preferredNamespacePrefix "${prefix}" ; vann:preferredNamespaceUri <onto/${slug}#> .`,
    ':Activo a owl:Class ; rdfs:comment "Clase de relleno."@en .',
    extra,
  ].join('\n') + '\n'
}

/** Serie con las versiones `{versión: [temas]}` en un catálogo. */
export function themedSeriesTurtle(slug: string, catalog: string, versions: Record<string, string[]>): string {
  const names = Object.keys(versions)
  const last = names[names.length - 1]
  const out = [
    '@prefix dcat: <http://www.w3.org/ns/dcat#> .',
    '@prefix dct:  <http://purl.org/dc/terms/> .',
    `<catalogo/${catalog}> dcat:dataset <dataset/${slug}> .`,
    `<dataset/${slug}> a dcat:DatasetSeries ; dct:type <vocab/tipo-dataset/sintetico> ;`,
    `    dct:title "Dataset ${slug}"@es ; dct:description "Serie de la prueba de pantallas."@es ; dcat:last <dataset/${slug}/${last}> .`,
  ]
  for (const [version, themes] of Object.entries(versions)) {
    out.push(
      `<dataset/${slug}/${version}> a dcat:Dataset ; dct:type <vocab/tipo-dataset/sintetico> ;`,
      `    dct:title "Dataset ${slug}"@es ; dct:description "Serie de la prueba de pantallas."@es ;`,
      `    dcat:version "${version}" ; dcat:inSeries <dataset/${slug}> ; dct:accessRights <${AR}PUBLIC> ;`,
      themes.length ? `    dcat:theme ${themes.map((t) => `<${t}>`).join(', ')} ;` : '',
      `    dcat:distribution <dataset/${slug}/${version}/csv> .`,
      `<dataset/${slug}/${version}/csv> a dcat:Distribution ; dct:accessRights <${AR}PUBLIC> ;`,
      `    dcat:mediaType <${IANA}text/csv> ; dcat:accessURL <dataset/${slug}/${version}/csv> .`,
    )
  }
  return out.join('\n') + '\n'
}

async function postTurtle(path: string, token: string, turtle: string): Promise<Response> {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'text/turtle' }, body: turtle, token })
}

export async function apiPublishScheme(token: string, catalog: string, slug: string, options: SchemeOptions = {}): Promise<void> {
  const response = await postTurtle(`/schemes?catalog=${catalog}`, token, schemeTurtle(slug, options))
  if (response.status !== 201) throw new Error(`publicar esquema ${slug}: ${response.status} ${(await response.text()).slice(0, 300)}`)
}

export async function apiPublishOntology(
  token: string,
  catalog: string,
  slug: string,
  options: { prefix?: string; version?: string; prior?: string; extra?: string } = {},
): Promise<void> {
  const response = await postTurtle(`/ontologies?catalog=${catalog}`, token, ontologyTurtle(slug, options))
  if (response.status !== 201) throw new Error(`publicar ontología ${slug}: ${response.status} ${(await response.text()).slice(0, 300)}`)
}

export async function apiPublishThemedSeries(token: string, catalog: string, slug: string, versions: Record<string, string[]>): Promise<number> {
  const response = await postTurtle('/datasets', token, themedSeriesTurtle(slug, catalog, versions))
  return response.status
}

/** `DELETE` de un recurso: devuelve el código (204, 409…). */
export async function apiDelete(token: string, path: string): Promise<number> {
  return (await api(path, { method: 'DELETE', token })).status
}

/** URI base de las pruebas (la `BASE_URI` del backend), sacada de un catálogo. */
export async function baseUri(): Promise<string> {
  const catalogs = (await (await api('/catalogs')).json()) as { items: { uri: string }[] }
  return catalogs.items[0].uri.replace(/catalogo\/[^/]+$/, '')
}

// --- Ontologías externas y sus versiones (decisión 51) ------------------------------------

export const EXTERNALS = {
  /** Se sustituye en las pruebas (y cambia de título). */
  saref: { slug: 'saref', iri: 'https://saref.etsi.org/core/' },
  /** No se sustituye nunca con éxito: es la «externa sin versiones». */
  d3f: { slug: 'd3f', iri: 'http://d3fend.mitre.org/ontologies/d3fend.owl' },
} as const

export interface ExternalVersion {
  number: number
  uri: string
  current: boolean
  version_info: string | null
  notes: string | null
  metrics: { classes: number } | null
}

export interface ExternalDetail {
  slug: string
  uri: string
  title: string | null
  prefix: string | null
  namespace: string | null
  publisher: string | null
  versions: ExternalVersion[]
  current_version: ExternalVersion | null
}

export async function externalDetail(slug: string): Promise<ExternalDetail> {
  const response = await api(`/ontologies/externas/${slug}`)
  if (response.status !== 200) throw new Error(`ficha de la externa ${slug}: ${response.status}`)
  return (await response.json()) as ExternalDetail
}

/** Un fichero Turtle sintético de una externa: tres clases suyas y una propiedad. */
export function externalOntologyTurtle(iri: string, tag: string, namespace: string = iri): string {
  return (
    [
      '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
      '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .',
      `<${iri}> a owl:Ontology .`,
      `<${namespace}Marcador${tag}> a owl:Class ; rdfs:label "Marcador ${tag}"@en .`,
      `<${namespace}Sensor${tag}> a owl:Class ; rdfs:subClassOf <${namespace}Marcador${tag}> .`,
      `<${namespace}Actuador${tag}> a owl:Class .`,
      `<${namespace}tiene${tag}> a owl:ObjectProperty .`,
    ].join('\n') + '\n'
  )
}

/** Sustituye una externa por la API (multipart). Devuelve el estado y el cuerpo. */
export async function apiReplaceExternal(
  token: string,
  slug: string,
  fields: Record<string, string>,
  file: { name: string; mimeType: string; text: string },
): Promise<{ status: number; body: Record<string, unknown> }> {
  const form = new FormData()
  for (const [name, value] of Object.entries(fields)) form.append(name, value)
  form.append('file', new Blob([file.text], { type: file.mimeType }), file.name)
  const response = await api(`/ontologies/externas/${slug}/versions`, { method: 'POST', body: form, token })
  return { status: response.status, body: (await response.json()) as Record<string, unknown> }
}

/** Si la externa aún no tiene versiones, la sustituye una vez (no hace nada si ya las tiene). */
export async function ensureExternalVersion(token: string, slug: keyof typeof EXTERNALS = 'saref'): Promise<ExternalDetail> {
  const current = await externalDetail(slug)
  if (current.versions.length > 0) return current
  const { iri } = EXTERNALS[slug]
  const result = await apiReplaceExternal(
    token,
    slug,
    { title: current.title ?? slug, prefix: current.prefix ?? slug, namespace: current.namespace ?? iri },
    { name: 'o.ttl', mimeType: 'text/turtle', text: externalOntologyTurtle(iri, Math.random().toString(16).slice(2, 8)) },
  )
  if (result.status !== 201) throw new Error(`sustituir ${slug}: ${result.status} ${JSON.stringify(result.body).slice(0, 300)}`)
  return externalDetail(slug)
}
