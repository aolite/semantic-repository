/**
 * Tipos de la API.
 *
 * Copiados a mano del contrato `backend/openapi.json` (versión 0.1.0, con las
 * rutas del catálogo de la fase 2 y las de vocabularios y ontologías de la
 * fase 3). Si el contrato cambia, hay que actualizarlos aquí. Cada tipo indica
 * el esquema de `components.schemas` del que sale.
 *
 * Los tipos de la fase 4 (FAIR, descargas, SPARQL y consultas guardadas) salen
 * del contrato de la fase (sección 5) y se escribieron antes de que el backend
 * regenerase `openapi.json`: la prueba de contrato de `qa` los contrasta con el
 * OpenAPI real en la integración.
 *
 * Los de la decisión 49 (catálogos, edición y bajas) salen del `openapi.json`
 * de la PR del contrato; las pruebas de contrato del backend
 * (`backend/tests/test_contracts_fase2.py` y `test_contracts_fase3.py`)
 * comprueban que coinciden.
 *
 * Los de la decisión 50 (vocabularios y ontologías en los catálogos) salen del
 * `openapi.json` de la rama del backend de esa decisión; los campos nuevos
 * que el contrato no exige van con `?:`.
 */

/** Esquema `Role`: roles con cuenta. El lector es anónimo y no tiene token. */
export type Role = 'miembro' | 'editor' | 'admin'

/** Esquema `Token`: respuesta de `POST /auth/token` (OAuth2 password flow). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  /** Validez del token en segundos. */
  expires_in: number
  role: Role
}

/** Esquema `UserRead`: respuesta de `GET /auth/me`. */
export interface CurrentUser {
  /** UUID. */
  id: string
  username: string
  role: Role
  is_active: boolean
  /** Fecha y hora ISO 8601. */
  created_at: string
  /** Fecha y hora ISO 8601. */
  updated_at: string
}

/** Esquema `HealthStatus`: respuesta de `GET /health`. */
export interface HealthResponse {
  status: 'ok'
  /** Versión del backend (`project.version` de su pyproject). */
  version?: string
  /** Commit desplegado (`APP_COMMIT`), o null si no se indicó. */
  commit?: string | null
}

/* ------------------------------------------------------------------------ */
/* Catálogo (fase 2): esquemas de `backend/openapi.json` de la fase 2.       */
/* ------------------------------------------------------------------------ */

/** Slugs de dominio (enum de `DomainRef.slug` y del filtro `domain`). */
export type DomainSlug = 'it' | 'ot' | 'pqc' | 'ia'

/**
 * Esquema `IngestErrorResponse`: error de `POST /datasets` (formulario «Nueva
 * versión»), `/ontologies` y `/schemes`, y 422 de los formularios JSON de
 * catálogos y datasets (decisión 49).
 */
export interface IngestErrorResponse {
  detail: string
  /**
   * `limit`: se ha superado un límite de la ingesta (tripletas, tamaño, IRI, profundidad o tiempo).
   * `catalog` (422): el catálogo indicado no existe o está dado de baja.
   * `version_removed` / `version_immutable` (409, fase 4): falta o cambia una versión ya publicada.
   * `withdrawn` (409): el slug es de un recurso dado de baja y no se reutiliza.
   * `catalog_conflict` (409): la serie, el esquema o la ontología ya está en otro catálogo (se mueve con `PATCH`).
   * Decisión 50: `prefix_withdrawn` (409, prefijo VANN de un recurso dado de baja),
   * `concepts_removed` (409, faltan conceptos ya publicados), `concept_reactivated` (409,
   * reactivar un concepto retirado), `replacement` (422, sustituto que no es un concepto vivo)
   * y `deprecated_theme` (422, temas retirados, con `issues[].replaced_by`). Segunda ronda:
   * `prefix_in_use` (409, prefijo VANN de otro recurso vivo, en `issues[].value`) y
   * `unknown_theme` (422, tema de `{BASE_URI}vocab/` que no es un concepto de un esquema vivo).
   * Decisión 51 (sustituir una ontología externa): `structure` (422) también si un campo del
   * formulario no es válido (su nombre en `issues[].path`) y `version_exists` (409, otra
   * sustitución se ha adelantado; no se escribe nada).
   */
  kind: IngestErrorKind
  issues: IngestIssue[]
  /** Informe SHACL en texto (solo `kind=shacl`). */
  report: string | null
}

/** Valores de `IngestErrorResponse.kind`. */
export type IngestErrorKind = 'syntax' | 'structure' | 'uri' | 'shacl' | 'limit' | 'catalog' | 'version_removed' | 'version_immutable' | 'withdrawn' | 'catalog_conflict' | 'prefix_withdrawn' | 'prefix_in_use' | 'concepts_removed' | 'concept_reactivated' | 'replacement' | 'deprecated_theme' | 'unknown_theme' | 'version_exists'

/** Esquema `IngestIssue`. */
export interface IngestIssue {
  message: string
  focus_node: string | null
  path: string | null
  value: string | null
  severity: string
  source_shape: string | null
  /** Solo con `kind=deprecated_theme`: sustitutos (`dct:isReplacedBy`) del tema retirado (`value`). */
  replaced_by?: string[]
}

/** Esquema `ErrorResponse`. */
export interface ErrorResponse {
  detail: string
}

/** Esquema `AccessRights`: `dct:accessRights`; `code` es la entrada de la tabla de la UE. */
export interface AccessRights {
  uri: string
  /** PUBLIC, RESTRICTED, NON_PUBLIC…; null si la IRI no es de esa tabla. */
  code: string | null
}

/**
 * Esquema `DomainRef`: concepto `{BASE_URI}vocab/dominio/{slug}`, el
 * `dct:subject` del esquema de los temas del dataset (o del propio esquema).
 */
export interface DomainRef {
  slug: DomainSlug
  /** IRI del concepto de dominio, no la del esquema de los temas. */
  uri: string
  label: string | null
}

/** Esquema `ThemeRef`: concepto SKOS de `dcat:theme`. */
export interface ThemeRef {
  uri: string
  label: string | null
  /** IRI del esquema (skos:inScheme). */
  scheme: string | null
}

/** Esquema `ResourceRef`: IRI (null si es un nodo en blanco) y etiqueta. */
export interface ResourceRef {
  uri: string | null
  label: string | null
}

/** Esquema `DatasetCard`: tarjeta de la pantalla Catálogo. */
export interface DatasetCard {
  slug: string
  uri: string
  title: string | null
  description: string | null
  domain: DomainRef | null
  domains: DomainRef[]
  themes: ThemeRef[]
  access_rights: AccessRights | null
  /** Tipos IANA de las distribuciones o, si no tienen, su `dct:title`. */
  formats: string[]
  current_version: string | null
  synthetic: boolean
  /** `total` de la última evaluación FAIR `done` de la versión actual (fase 4). */
  fair_total?: number | null
  /** Catálogo del dataset (decisión 49); null si no está en ninguno. */
  catalog?: CatalogRef | null
}

/** Esquema `DatasetPage`: respuesta de `GET /datasets`. */
export interface DatasetPage {
  items: DatasetCard[]
  total: number
  page: number
  page_size: number
}

/** Esquema `VersionRef`. */
export interface VersionRef {
  uri: string
  version: string | null
}

/** Esquema `DistributionRead`. */
export interface DistributionRead {
  uri: string
  title: string | null
  media_type: string | null
  media_type_uri: string | null
  access_url: string | null
  /** De la distribución o, si no tiene, de la versión. */
  access_rights: AccessRights | null
  /** Cómo se descarga (fase 4, decisión 40). */
  download: DistributionDownload
  /** Ruta del fichero (`{BASE_URI}dataset/{slug}/{version}/{dist}/fichero`) si `download` es `open` o `authenticated`. */
  download_url?: string | null
  byte_size?: number | null
  sha256?: string | null
}

/**
 * Descarga de una distribución: `open` (PUBLIC con fichero), `authenticated`
 * (RESTRICTED con fichero, miembro o superior), `metadata_only` (NON_PUBLIC,
 * defensa) o `unavailable` (sin fichero).
 */
export type DistributionDownload = 'open' | 'authenticated' | 'metadata_only' | 'unavailable'

/**
 * Respuesta de `POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link`:
 * enlace firmado y de vida corta. El contrato de la fase da los campos
 * `{url, expires_at}`; el nombre del esquema se confirma con el OpenAPI.
 */
export interface DownloadLink {
  url: string
  /** Fecha y hora ISO 8601. */
  expires_at: string
}

/** Estado de la evaluación FAIR de una versión. */
export type FairStatus = 'pending' | 'running' | 'done' | 'failed' | 'not_evaluated'

/**
 * Esquema `FairSummary`: resumen de la evaluación de F-UJI. Las puntuaciones
 * (0-100) y el nivel de madurez salen tal cual de F-UJI.
 */
export interface FairSummary {
  status: FairStatus
  total: number | null
  findable: number | null
  accessible: number | null
  interoperable: number | null
  reusable: number | null
  /** Nivel de madurez que devuelve F-UJI, sin umbrales propios (decisión 45). */
  maturity: string | null
  /** Nombre y versión del evaluador. */
  evaluator: string | null
  /** Fecha y hora ISO 8601. */
  evaluated_at: string | null
  /** Informe completo (`GET /datasets/{slug}/versions/{version}/fair/report`). */
  report_url: string | null
}

/** Esquema `ProvenanceStep`: paso PROV-O, del origen a la actividad que generó la versión. */
export interface ProvenanceStep {
  kind: 'activity' | 'entity'
  uri: string | null
  label: string | null
  /** prov:wasAssociatedWith (actividades). */
  agents: ResourceRef[]
}

/** Esquema `DcatMetadata`. */
export interface DcatMetadata {
  publisher: ResourceRef | null
  contact_point: ResourceRef | null
  license: ResourceRef | null
  access_rights: AccessRights | null
  issued: string | null
  modified: string | null
  is_referenced_by: ResourceRef[]
  themes: ThemeRef[]
  conforms_to: ResourceRef[]
}

/** Esquema `VersionDetail`. */
export interface VersionDetail {
  uri: string
  version: string | null
  title: string | null
  description: string | null
  keywords: string[]
  version_notes: string | null
  previous_version: VersionRef | null
  /** IRI de la serie. */
  in_series: string
  synthetic: boolean
  distributions: DistributionRead[]
  provenance: ProvenanceStep[]
  metadata: DcatMetadata
  /** Evaluación FAIR (fase 4); null si no aplica. */
  fair?: FairSummary | null
}

/** Esquema `VersionSummary`: entrada del historial (de la más reciente a la más antigua). */
export interface VersionSummary {
  version: string | null
  uri: string
  notes: string | null
  issued: string | null
  modified: string | null
  /** Es la versión actual (dcat:last). */
  current: boolean
  /** false si solo se conoce por un dcat:previousVersion. */
  described: boolean
}

/** Esquema `DatasetDetail`: respuesta de `GET /datasets/{slug}`. */
export interface DatasetDetail {
  slug: string
  uri: string
  title: string | null
  description: string | null
  /** Catálogo del dataset (decisión 49); null si no está en ninguno. */
  catalog?: CatalogRef | null
  /** `dct:publisher` de la serie (`label` es lo que edita `publisher_name`); null si no lo declara. */
  publisher?: ResourceRef | null
  synthetic: boolean
  domain: DomainRef | null
  domains: DomainRef[]
  current_version: string | null
  /** null si la serie no tiene versiones. */
  version: VersionDetail | null
  versions: VersionSummary[]
}

/** Valores de `?format=` de `GET /datasets/{slug}/rdf`. */
export type RdfFormat = 'turtle' | 'jsonld'

/* ------------------------------------------------------------------------ */
/* Vocabularios y ontologías (fase 3).                                       */
/* ------------------------------------------------------------------------ */

/** Tipo de tarjeta de `GET /vocabularies` (enum de `VocabularyCard.kind` y del filtro `kind`). */
export type VocabularyKind = 'own' | 'external' | 'skos_corp' | 'skos_domain'

/** Estado de una ontología o esquema: Publicada, Borrador o Referenciada. */
export type VocabularyStatus = 'published' | 'draft' | 'referenced'

/** Esquema `MetricsSummary`: resumen de la tarjeta (solo ontologías propias). */
export interface MetricsSummary {
  classes: number
  /** Propiedades de objeto más propiedades de datos. */
  properties: number
}

/** Esquema `VocabularyCard`. */
export interface VocabularyCard {
  kind: VocabularyKind
  /**
   * Slug de la ontología o del esquema (sin `corp/`). En las externas
   * (decisión 51), el de sus versiones (su prefijo VANN); null si no tiene prefijo.
   */
  slug: string | null
  uri: string
  rdf_type: 'owl:Ontology' | 'skos:ConceptScheme'
  title: string | null
  /** vann:preferredNamespacePrefix (sin los dos puntos). */
  prefix: string | null
  namespace: string | null
  description: string | null
  status: VocabularyStatus
  version: string | null
  /** Ontologías propias con métricas calculadas y externas con versión actual (decisión 51); null en el resto. */
  metrics: MetricsSummary | null
  /** Número de conceptos (solo esquemas). */
  concepts: number | null
  /** Catálogo de la ontología propia o del esquema (decisión 50); null en las externas. */
  catalog?: CatalogRef | null
  /** Dominio (dct:subject): solo lo tienen los esquemas de dominio. */
  domain: DomainRef | null
  synthetic: boolean
}

/** Esquema `VocabularyCounts`. */
export interface VocabularyCounts {
  own: number
  external: number
  skos_corp: number
  skos_domain: number
}

/** Esquema `VocabularyPage`: respuesta de `GET /vocabularies`. */
export interface VocabularyPage {
  items: VocabularyCard[]
  /** Tarjetas que cumplen los filtros. */
  total: number
  /** Recuento por tipo de todo el repositorio, sin aplicar `q`, `kind` ni `domain`. */
  counts: VocabularyCounts
}

/** Esquema `OntologyMetadata`: metadatos VANN y DCT de la versión. */
export interface OntologyMetadata {
  prefix: string | null
  namespace: string | null
  title: string | null
  description: string | null
  creators: ResourceRef[]
  contributors: ResourceRef[]
  publisher: ResourceRef | null
  license: ResourceRef | null
  rights: string | null
  issued: string | null
  modified: string | null
  created: string | null
}

/** Esquema `OntologyVersionRef`. */
export interface OntologyVersionRef {
  version_iri: string
  version: string | null
}

/** Esquema `OntologyVersionSummary`: entrada del historial. */
export interface OntologyVersionSummary {
  version: string | null
  version_iri: string
  /** adms:versionNotes. */
  notes: string | null
  issued: string | null
  current: boolean
  /** false si la versión solo se conoce por un owl:priorVersion. */
  described: boolean
}

/** Esquema `OntologyVersioning`. */
export interface OntologyVersioning {
  version: string | null
  version_iri: string
  current_version: string | null
  prior_version: OntologyVersionRef | null
  backward_compatible_with: OntologyVersionRef[]
  history: OntologyVersionSummary[]
}

/** Esquema `OntologyMetricsRead`. */
export interface OntologyMetricsRead {
  classes: number
  object_properties: number
  data_properties: number
  annotation_properties: number
  individuals: number
  /** Aproximado. */
  logical_axioms: number
  /** owl:imports declarados (no se descargan). */
  imports: number
  /** No se calcula: siempre null. */
  dl_expressivity?: null
}

/** Esquema `OwlProfile`. */
export interface OwlProfile {
  name: 'OWL 2 DL' | 'OWL 2 Full'
  /** Perfiles compatibles, aproximados por constructores. */
  compatible: ('OWL 2 EL' | 'OWL 2 QL' | 'OWL 2 RL')[]
  approximate?: boolean
}

/** Esquema `ConsistencyRead`. */
export interface ConsistencyRead {
  /** Nombre del razonador (hoy, Pellet). */
  reasoner: string
  /** null si el razonador no pudo ejecutarse. */
  consistent: boolean | null
  unsatisfiable_classes: number | null
  /** IRIs de las clases insatisfacibles. */
  unsatisfiable: string[]
  /** Motivo si `consistent` es false o null. */
  detail: string | null
  /** Siempre false: se razona sin las ontologías importadas. */
  includes_imports?: boolean
}

/** Esquema `DocumentationCoverageRead`. */
export interface DocumentationCoverageRead {
  documented: number
  total: number
  /** % de clases y propiedades con rdfs:comment. */
  percent: number | null
  classes_documented: number
  classes_total: number
  properties_documented: number
  properties_total: number
}

/** Esquema `ImportRef`. */
export interface ImportRef {
  uri: string
  title: string | null
  prefix: string | null
  version: string | null
  /** La ontología importada está descrita en las externas. */
  known: boolean
}

/** Esquema `AlignmentMapping`. */
export interface AlignmentMapping {
  source: string
  target: string
}

/** Esquema `Alignment`: axiomas hacia términos de una ontología externa, por relación. */
export interface Alignment {
  /** null si no se reconoce la ontología. */
  target_ontology: string | null
  title: string | null
  prefix: string | null
  /** IRI de la relación (rdfs:subClassOf, skos:exactMatch…). */
  relation: string
  /** rdfs:comment o dct:description de la anotación del axioma. */
  scope: string | null
  /** owl:versionInfo de la ontología destino. */
  version: string | null
  count: number
  mappings: AlignmentMapping[]
}

/** Esquema `DatasetVersionUse`. */
export interface DatasetVersionUse {
  version: string | null
  uri: string
  /** IRI exacta de dct:conformsTo, si aplica. */
  conforms_to: string | null
}

/** Esquema `DatasetUse`. */
export interface DatasetUse {
  slug: string
  uri: string
  title: string | null
  versions: DatasetVersionUse[]
}

/** Esquema `OntologyUse`. */
export interface OntologyUse {
  slug: string
  uri: string
  title: string | null
  versions: string[]
}

/** Esquema `SchemeRef`. */
export interface SchemeRef {
  uri: string
  slug: string
  corp: boolean
  label: string | null
}

/** Esquema `SubjectRef`: `dct:subject` de una ontología (un esquema SKOS o un concepto). */
export interface SubjectRef {
  uri: string
  type: 'scheme' | 'concept' | 'unknown'
  label: string | null
  scheme: SchemeRef | null
}

/** Esquema `OntologyDetail`: respuesta de `GET /ontologies/{slug}`. */
export interface OntologyDetail {
  slug: string
  uri: string
  kind: 'own'
  status: VocabularyStatus
  synthetic: boolean
  title: string | null
  description: string | null
  metadata: OntologyMetadata
  versioning: OntologyVersioning
  /** null si no se han calculado. */
  metrics: OntologyMetricsRead | null
  profile: OwlProfile | null
  consistency: ConsistencyRead | null
  documentation: DocumentationCoverageRead | null
  metrics_computed_at: string | null
  metrics_tool: string | null
  imports: ImportRef[]
  alignments: Alignment[]
  /** Series con alguna versión con dct:conformsTo hacia la ontología o una de sus versiones. */
  used_by_datasets: DatasetUse[]
  /** Esquemas SKOS usados (dct:subject). */
  subjects: SubjectRef[]
  /** Catálogo de la ontología (decisión 50). */
  catalog?: CatalogRef | null
}

/** Esquema `SchemeMetadata`. */
export interface SchemeMetadata {
  creators: ResourceRef[]
  publisher: ResourceRef | null
  license: ResourceRef | null
  issued: string | null
  modified: string | null
}

/** Esquema `ConceptNode`: nodo del árbol de un esquema. */
export interface ConceptNode {
  uri: string
  slug: string | null
  label: string | null
  /** skos:topConceptOf o skos:hasTopConcept. */
  top_concept: boolean
  /** skos:altLabel por idioma. */
  alt_labels: LangLiteral[]
  /** Concepto retirado (`owl:deprecated true`, decisión 50). */
  deprecated?: boolean
  /** skos:narrower e inversa de skos:broader. */
  children: ConceptNode[]
}

/** Esquema `SchemeDetail`: respuesta de `GET /schemes/{slug}` y `/schemes/corp/{slug}`. */
/**
 * Tipo de un esquema: corporativo, de dominio o auxiliar (`vocab/dominio` y
 * `vocab/tipo-dataset`, sin tarjeta en `/vocabularies`).
 */
export type SchemeKind = 'skos_corp' | 'skos_domain' | 'auxiliary'

export interface SchemeDetail {
  slug: string
  corp: boolean
  kind: SchemeKind
  uri: string
  title: string | null
  description: string | null
  prefix: string | null
  namespace: string | null
  version: string | null
  status: VocabularyStatus
  synthetic: boolean
  /** Dominio del esquema (dct:subject). */
  domain: DomainRef | null
  /** Placeholder del prototipo: siempre null hasta que se decida (decisión abierta 11). */
  responsible?: null
  metadata: SchemeMetadata
  concept_count: number
  /** Conceptos raíz con sus hijos. */
  tree: ConceptNode[]
  /** Catálogo del esquema (decisión 50); null en los auxiliares, que no están en ningún catálogo. */
  catalog?: CatalogRef | null
}

/** Esquema `LangLiteral`. */
export interface LangLiteral {
  value: string
  /** es, ca, en…; null si no tiene. */
  lang: string | null
}

/** Esquema `ConceptRef`. */
export interface ConceptRef {
  uri: string
  /** skos:prefLabel (es) si el concepto está cargado. */
  label: string | null
  /** IRI del esquema (skos:inScheme). */
  scheme: string | null
}

/** Esquema `ConceptUsage`. */
export interface ConceptUsage {
  /** Series con versiones con dcat:theme. */
  datasets: DatasetUse[]
  /** Ontologías con dct:subject. */
  ontologies: OntologyUse[]
}

/** Esquema `ConceptDetail`: respuesta de `GET /schemes/{slug}/concepts/{concept}`. */
export interface ConceptDetail {
  uri: string
  slug: string
  scheme: SchemeRef
  /** skos:prefLabel preferida (es). */
  pref_label: string | null
  pref_labels: LangLiteral[]
  alt_labels: LangLiteral[]
  definition: string | null
  definitions: LangLiteral[]
  top_concept: boolean
  broader: ConceptRef[]
  narrower: ConceptRef[]
  related: ConceptRef[]
  exact_match: string[]
  close_match: string[]
  used_by: ConceptUsage
  /** Concepto retirado (`owl:deprecated true`, decisión 50). */
  deprecated?: boolean
  /** Sustitutos del concepto retirado (`dct:isReplacedBy`, decisión 50). */
  replaced_by?: ConceptRef[]
}

/** Valores de `?format=` de `/ontologies/{slug}/rdf` y `/schemes/…/rdf`. */
export type VocabRdfFormat = 'turtle' | 'rdfxml' | 'jsonld'

/* ------------------------------------------------------------------------ */
/* Consola SPARQL (fase 4).                                                  */
/* ------------------------------------------------------------------------ */

/**
 * Esquema `SavedQuery`: consulta de referencia (de `semantic/consultas/`,
 * visible para todos, `id` es su slug y `{BASE_URI}` ya va sustituido) o
 * personal (de su dueño).
 */
export interface SavedQuery {
  id: string
  title: string
  hint: string | null
  query: string
  kind: 'reference' | 'personal'
  created_at: string | null
  updated_at: string | null
}

/** Cuerpo de `POST /sparql/queries` (miembro). */
export interface SavedQueryCreate {
  /** 1-120 caracteres. */
  title: string
  /** 0-200 caracteres. */
  hint?: string | null
  /** 1 byte a 20 KB. */
  query: string
}

/* ------------------------------------------------------------------------ */
/* Catálogos, edición y bajas (decisión 49).                                 */
/* ------------------------------------------------------------------------ */

/** Esquema `CatalogRef`: catálogo `{BASE_URI}catalogo/{slug}` de un dataset. */
export interface CatalogRef {
  slug: string
  uri: string
  title: string | null
}

/** Esquema `CatalogSummary`: entrada de `GET /catalogs`. */
export interface CatalogSummary {
  slug: string
  uri: string
  title: string | null
  description: string | null
  publisher: ResourceRef | null
  /** Número de datasets (series) del catálogo. */
  dataset_count: number
  /** Número de esquemas SKOS del catálogo (decisión 50). */
  scheme_count?: number
  /** Número de ontologías propias del catálogo (decisión 50). */
  ontology_count?: number
}

/** Esquema `CatalogPage`: respuesta de `GET /catalogs` (sin el raíz ni las bajas). */
export interface CatalogPage {
  items: CatalogSummary[]
  total: number
}

/** Esquema `CatalogDatasetRef`: serie de un catálogo. */
export interface CatalogDatasetRef {
  slug: string
  uri: string
  title: string | null
}

/** Esquema `CatalogDetail`: `GET /catalogs/{slug}`, `POST /catalogs` y `PATCH /catalogs/{slug}`. */
export interface CatalogDetail {
  slug: string
  uri: string
  title: string | null
  description: string | null
  publisher: ResourceRef | null
  dataset_count: number
  /** Número de esquemas SKOS del catálogo (decisión 50). */
  scheme_count?: number
  /** Número de ontologías propias del catálogo (decisión 50). */
  ontology_count?: number
  /** Series del catálogo, por título. */
  datasets: CatalogDatasetRef[]
  /** Esquemas SKOS del catálogo, por título (decisión 50). */
  schemes?: CatalogSchemeRef[]
  /** Ontologías propias del catálogo, por título (decisión 50). */
  ontologies?: CatalogOntologyRef[]
}

/** Esquema `CatalogSchemeRef`: esquema SKOS de un catálogo (decisión 50). */
export interface CatalogSchemeRef {
  slug: string
  corp: boolean
  uri: string
  title: string | null
}

/** Esquema `CatalogOntologyRef`: ontología propia de un catálogo (decisión 50). */
export interface CatalogOntologyRef {
  slug: string
  uri: string
  /** `dct:title` de su versión actual. */
  title: string | null
}

/** Esquema `CatalogCreate`: cuerpo de `POST /catalogs`. */
export interface CatalogCreate {
  /** Minúsculas ASCII, dígitos y guiones; no cambia. */
  slug: string
  /** Se guarda en español (`@es`). */
  title: string
  /** Se guarda en español (`@es`). */
  description: string
  publisher_name: string
}

/** Esquema `CatalogUpdate`: cuerpo de `PATCH /catalogs/{slug}` (solo cambian los campos presentes). */
export interface CatalogUpdate {
  title?: string | null
  description?: string | null
  publisher_name?: string | null
}

/**
 * Esquema `ConflictResponse`: 409 del CRUD de catálogos, datasets, esquemas y
 * ontologías. `slug_in_use` y `withdrawn` al crear; `catalog_not_empty` (con
 * `datasets` y `resources`) al dar de baja un catálogo que no está vacío;
 * `in_use` (con `used_by`, decisión 50) al dar de baja un esquema o una
 * ontología que usan recursos vivos.
 */
export interface ConflictResponse {
  detail: string
  kind: 'slug_in_use' | 'withdrawn' | 'catalog_not_empty' | 'in_use'
  /** Solo con `catalog_not_empty`: URIs de las series que siguen en el catálogo. */
  datasets?: string[]
  /** Solo con `catalog_not_empty`: URIs de los esquemas y ontologías que siguen en el catálogo. */
  resources?: string[]
  /** Solo con `in_use`: los recursos vivos que lo usan. */
  used_by?: UsageRef[]
}

/** Esquema `UsageRef`: un uso que impide dar de baja un esquema o una ontología (409 `in_use`). */
export interface UsageRef {
  /** Quién lo usa: versión de dataset, versión de ontología (`owl:versionIRI`) o concepto de otro esquema. */
  uri: string
  resource: 'dataset' | 'ontology' | 'scheme'
  /** Propiedad del uso (`dcat:theme`, `dct:subject`, `skos:related`, `owl:imports`…); null si usa un término. */
  via: string | null
  /** Concepto, ontología, versión o término usado. */
  target: string
}

/**
 * Esquema `ForbiddenResponse`: 403. Con `kind: "not_managed"` (decisión 50),
 * el recurso es una ontología externa o un esquema auxiliar y no se gestiona
 * desde la aplicación, con ningún rol; sin `kind`, falta el rol.
 */
export interface ForbiddenResponse {
  detail: string
  kind?: 'not_managed' | null
}

/** Esquema `GoneResponse`: 410, ficha mínima (lápida) de un recurso dado de baja. */
export interface GoneResponse {
  detail: string
  uri: string
  resource: 'catalog' | 'dataset' | 'scheme' | 'ontology'
  title: string | null
  /** `prov:invalidatedAtTime` (xsd:dateTime). */
  withdrawn_at: string | null
}

/** Esquema `DatasetCreate`: cuerpo de `POST /catalogs/{slug}/datasets` (serie sin versiones). */
export interface DatasetCreate {
  slug: string
  title: string
  description: string
  publisher_name?: string | null
}

/** Esquema `DatasetUpdate`: cuerpo de `PATCH /datasets/{slug}`; `catalog` mueve el dataset. */
export interface DatasetUpdate {
  title?: string | null
  description?: string | null
  publisher_name?: string | null
  catalog?: string | null
}

/** Esquema `IngestResult`: respuesta de `POST /datasets` (201 nueva, 200 sustituida). */
export interface IngestResult {
  slug: string
  uri: string
  graph: string
  versions: string[]
  triples: number
  created: boolean
  changed: boolean
}

/* ------------------------------------------------------------------------ */
/* Vocabularios y ontologías en los catálogos (decisión 50).                 */
/* ------------------------------------------------------------------------ */

/** Esquema `SchemeUpdate`: cuerpo de `PATCH /schemes/…` (solo cambian los campos presentes). */
export interface SchemeUpdate {
  /** `dct:title` y `skos:prefLabel` en español; los demás idiomas no cambian. */
  title?: string | null
  /** `dct:description` en español; los demás idiomas no cambian. */
  description?: string | null
  publisher_name?: string | null
  /** Slug del catálogo de destino (mover el esquema). */
  catalog?: string | null
}

/** Esquema `ExternalVersionRead`: versión `{BASE_URI}onto/externas/{slug}/{n}` de una ontología externa (decisión 51). */
export interface ExternalVersionRead {
  /** n: número de sustitución (1, 2, 3…). */
  number: number
  /** dcat:version: n como texto. */
  version: string
  uri: string
  /** owl:versionInfo: la versión del publicador. */
  version_info: string | null
  /** prov:generatedAtTime (hora del servidor). */
  generated_at: string | null
  /** dcat:previousVersion (la n-1). */
  previous_version: string | null
  /** adms:versionNotes (es). */
  notes: string | null
  /** Es la versión actual (dcat:hasCurrentVersion). */
  current: boolean
  /** null si no se han calculado. */
  metrics: OntologyMetricsRead | null
  profile: OwlProfile | null
  consistency: ConsistencyRead | null
  documentation: DocumentationCoverageRead | null
  metrics_computed_at: string | null
  metrics_tool: string | null
}

/** Esquema `ExternalOntologyDetail`: respuesta de `GET /ontologies/externas/{slug}` (decisión 51). */
export interface ExternalOntologyDetail {
  slug: string
  /** IRI oficial de la ontología. */
  uri: string
  kind: 'external'
  status: 'referenced'
  title: string | null
  description: string | null
  prefix: string | null
  namespace: string | null
  /** owl:versionInfo de la referencia (la actual). */
  version: string | null
  /** foaf:name del dct:publisher. */
  publisher: string | null
  /** null si nunca se ha sustituido (solo referencia, sin métricas). */
  current_version: ExternalVersionRead | null
  /** De la más reciente a la más antigua. */
  versions: ExternalVersionRead[]
}

/** Esquema `ExternalReplaceResult`: respuesta 201 de `POST /ontologies/externas/{slug}/versions`. */
export interface ExternalReplaceResult {
  slug: string
  uri: string
  number: number
  version: string
  version_uri: string
  graph: string
  previous_version: string | null
  generated_at: string
  triples: number
  metrics: OntologyMetricsRead
  profile: OwlProfile
  consistency: ConsistencyRead
  documentation: DocumentationCoverageRead
}

/** Esquema `OntologyUpdate`: cuerpo de `PATCH /ontologies/{slug}` (solo mueve de catálogo). */
export interface OntologyUpdate {
  catalog: string
}

/** Esquema `SchemeIngestResult`: respuesta de `POST /schemes` (201 nuevo, 200 sustituido). */
export interface SchemeIngestResult {
  slug: string
  corp: boolean
  uri: string
  graph: string
  concepts: number
  triples: number
  created: boolean
  changed: boolean
  /** URI del catálogo. */
  catalog?: string | null
}

/** Esquema `OntologyIngestResult`: respuesta de `POST /ontologies` (201 nueva, 200 sustituida). */
export interface OntologyIngestResult {
  slug: string
  uri: string
  version: string
  version_iri: string
  graph: string
  triples: number
  created: boolean
  changed: boolean
  /** false si la versión ya tenía métricas para el mismo contenido. */
  metrics_recomputed: boolean
  metrics: OntologyMetricsRead
  profile: OwlProfile
  consistency: ConsistencyRead
  documentation: DocumentationCoverageRead
  /** URI del catálogo. */
  catalog?: string | null
}
