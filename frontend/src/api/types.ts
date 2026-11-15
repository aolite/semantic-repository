/**
 * Tipos de la API.
 *
 * Copiados a mano del contrato `backend/openapi.json` (versión 0.1.0, con las
 * rutas del catálogo de la fase 2 y las de vocabularios y ontologías de la
 * fase 3). Si el
 * contrato cambia, hay que actualizarlos aquí. Cada tipo indica el esquema
 * de `components.schemas` del que sale.
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
}

/* ------------------------------------------------------------------------ */
/* Catálogo (fase 2): esquemas de `backend/openapi.json` de la fase 2.       */
/* ------------------------------------------------------------------------ */

/** Slugs de dominio (enum de `DomainRef.slug` y del filtro `domain`). */
export type DomainSlug = 'it' | 'ot' | 'pqc' | 'ia'

/**
 * Esquema `IngestErrorResponse`: error de `POST /datasets`, `/ontologies` y
 * `/schemes`. El cliente todavía no tiene pantallas de ingesta; se recoge para
 * que el tipo siga alineado con el contrato.
 */
export interface IngestErrorResponse {
  detail: string
  /** `limit`: se ha superado un límite de la ingesta (tripletas, tamaño, IRI, profundidad o tiempo). */
  kind: 'syntax' | 'structure' | 'uri' | 'shacl' | 'limit'
  issues: IngestIssue[]
  /** Informe SHACL en texto (solo `kind=shacl`). */
  report: string | null
}

/** Esquema `IngestIssue`. */
export interface IngestIssue {
  message: string
  focus_node: string | null
  path: string | null
  value: string | null
  severity: string
  source_shape: string | null
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
  /** Slug de la ontología o del esquema (sin `corp/`); null en las externas. */
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
  /** Ontologías propias con métricas calculadas; null en el resto. */
  metrics: MetricsSummary | null
  /** Número de conceptos (solo esquemas). */
  concepts: number | null
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
}

/** Valores de `?format=` de `/ontologies/{slug}/rdf` y `/schemes/…/rdf`. */
export type VocabRdfFormat = 'turtle' | 'rdfxml' | 'jsonld'
