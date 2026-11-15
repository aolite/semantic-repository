/**
 * Tipos de la API.
 *
 * Copiados a mano del contrato `backend/openapi.json` (versión 0.1.0, con las
 * rutas del catálogo de la fase 2). Si el
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

/** Esquema `DomainRef`: esquema SKOS `{BASE_URI}vocab/{slug}`. */
export interface DomainRef {
  slug: DomainSlug
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
