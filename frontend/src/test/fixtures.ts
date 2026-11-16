/**
 * Respuestas ficticias del catálogo con la forma de los esquemas del OpenAPI.
 * Solo para pruebas: los textos son de prueba, no datos del catálogo. Al estar
 * tipadas, el build falla si se desalinean de `src/api/types.ts`.
 */
import type {
  DatasetCard,
  DatasetDetail,
  DatasetPage,
  DcatMetadata,
  DistributionRead,
  FairSummary,
  VersionDetail,
  VersionSummary,
} from '../api'

const BASE = 'http://uri.test/itot/'
const RESTRICTED = 'http://publications.europa.eu/resource/authority/access-right/RESTRICTED'
const PUBLIC = 'http://publications.europa.eu/resource/authority/access-right/PUBLIC'

export const accessRestricted = { uri: RESTRICTED, code: 'RESTRICTED' }
export const accessPublic = { uri: PUBLIC, code: 'PUBLIC' }

export function cardFixture(overrides: Partial<DatasetCard> = {}): DatasetCard {
  return {
    slug: 'dataset-prueba',
    uri: `${BASE}dataset/dataset-prueba`,
    title: 'Dataset de prueba',
    description: 'Descripción de prueba.',
    domain: { slug: 'ot', uri: `${BASE}vocab/dominio/ot`, label: 'Dominio de prueba' },
    domains: [{ slug: 'ot', uri: `${BASE}vocab/dominio/ot`, label: 'Dominio de prueba' }],
    themes: [
      { uri: `${BASE}vocab/ot/tema-a`, label: 'Tema A', scheme: `${BASE}vocab/ot` },
      { uri: `${BASE}vocab/ot/tema-b`, label: 'Tema B', scheme: `${BASE}vocab/ot` },
    ],
    access_rights: accessRestricted,
    formats: ['application/vnd.tcpdump.pcap', 'text/csv', 'application/vnd.apache.parquet'],
    current_version: '2.1.0',
    synthetic: false,
    fair_total: null,
    ...overrides,
  }
}

export function pageFixture(items: DatasetCard[], overrides: Partial<DatasetPage> = {}): DatasetPage {
  return { items, total: items.length, page: 1, page_size: 100, ...overrides }
}

export function metadataFixture(overrides: Partial<DcatMetadata> = {}): DcatMetadata {
  return {
    publisher: { uri: null, label: 'Publicador de prueba' },
    contact_point: null,
    license: null,
    access_rights: accessRestricted,
    issued: null,
    modified: null,
    is_referenced_by: [],
    themes: [{ uri: `${BASE}vocab/ot/tema-a`, label: 'Tema A', scheme: `${BASE}vocab/ot` }],
    conforms_to: [{ uri: `${BASE}onto/prueba/1.0.0`, label: 'Ontología de prueba' }],
    ...overrides,
  }
}

const SERIES = `${BASE}dataset/dataset-prueba`

export function versionFixture(overrides: Partial<VersionDetail> = {}): VersionDetail {
  return {
    uri: `${SERIES}/2.1.0`,
    version: '2.1.0',
    title: 'Dataset de prueba',
    description: 'Descripción de prueba.',
    keywords: ['clave-a', 'clave-b'],
    version_notes: 'Notas de prueba de la 2.1.0.',
    previous_version: { uri: `${SERIES}/2.0.0`, version: '2.0.0' },
    in_series: SERIES,
    synthetic: false,
    distributions: [distributionFixture()],
    provenance: [
      { kind: 'activity', uri: null, label: 'Actividad origen', agents: [] },
      { kind: 'entity', uri: null, label: 'Entidad intermedia', agents: [] },
      { kind: 'activity', uri: `${BASE}actividad/final`, label: 'Actividad final', agents: [{ uri: null, label: 'Agente de prueba' }] },
    ],
    metadata: metadataFixture(),
    fair: null,
    ...overrides,
  }
}

/** Distribución restringida con fichero (`authenticated`) de la versión 2.1.0. */
export function distributionFixture(dist = 'a', overrides: Partial<DistributionRead> = {}): DistributionRead {
  const uri = `${SERIES}/2.1.0/${dist}`
  return {
    uri,
    title: 'Distribución A',
    media_type: 'text/csv',
    media_type_uri: 'http://www.iana.org/assignments/media-types/text/csv',
    access_url: uri,
    access_rights: accessRestricted,
    download: 'authenticated',
    download_url: `${uri}/fichero`,
    byte_size: 1024,
    sha256: '0'.repeat(64),
    ...overrides,
  }
}

/** Evaluación FAIR terminada con puntuaciones de prueba (no son las del prototipo). */
export function fairFixture(overrides: Partial<FairSummary> = {}): FairSummary {
  return {
    status: 'done',
    total: 41,
    findable: 11,
    accessible: 22,
    interoperable: 33,
    reusable: 44,
    maturity: '1.75',
    evaluator: 'evaluador-de-prueba 0.0.0',
    evaluated_at: '2000-01-02T03:04:05Z',
    report_url: '/datasets/dataset-prueba/versions/2.1.0/fair/report',
    ...overrides,
  }
}

/** Versión antigua: sin temas, procedencia ni distribuciones. */
export function oldVersionFixture(): VersionDetail {
  return versionFixture({
    uri: `${SERIES}/1.0.0`,
    version: '1.0.0',
    keywords: [],
    version_notes: 'Notas de prueba de la 1.0.0.',
    previous_version: null,
    distributions: [],
    provenance: [],
    metadata: metadataFixture({ themes: [], conforms_to: [] }),
  })
}

export function historyFixture(): VersionSummary[] {
  return ['2.1.0', '2.0.0', '1.0.0'].map((version, i) => ({
    version,
    uri: `${SERIES}/${version}`,
    notes: `Notas de prueba de la ${version}.`,
    issued: null,
    modified: null,
    current: i === 0,
    described: true,
  }))
}

export function detailFixture(overrides: Partial<DatasetDetail> = {}): DatasetDetail {
  return {
    slug: 'dataset-prueba',
    uri: SERIES,
    title: 'Dataset de prueba',
    description: 'Descripción de prueba.',
    synthetic: false,
    domain: { slug: 'ot', uri: `${BASE}vocab/dominio/ot`, label: 'Dominio de prueba' },
    domains: [{ slug: 'ot', uri: `${BASE}vocab/dominio/ot`, label: 'Dominio de prueba' }],
    current_version: '2.1.0',
    version: versionFixture(),
    versions: historyFixture(),
    ...overrides,
  }
}

export function textResponse(body: string, contentType: string, status = 200): Response {
  return new Response(body, { status, headers: { 'Content-Type': contentType } })
}
