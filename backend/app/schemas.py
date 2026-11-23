"""Esquemas Pydantic de entrada y salida de la API."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Role
from app.security import PASSWORD_MIN_LENGTH, has_control_chars
from app.uris import SLUG_PATTERN, DomainSlug

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - tipo OAuth2, no es un secreto
    expires_in: int = Field(description="Validez del token en segundos")
    role: Role


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        pattern=USERNAME_PATTERN,
        description="De 3 a 64 caracteres: minúsculas, dígitos, punto, guion y guion bajo",
    )
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)
    role: Role

    @field_validator("username", "password", mode="before")
    @classmethod
    def _no_control_chars(cls, value: object) -> object:
        # Se comprueba antes que el patrón: NUL y demás caracteres de control nunca
        # llegan a la base de datos (PostgreSQL rechaza NUL en texto).
        if isinstance(value, str) and has_control_chars(value):
            raise ValueError("no puede contener caracteres de control")
        return value


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None


class ComponentStatus(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthStatus(BaseModel):
    status: Literal["ok"]


class ReadinessStatus(BaseModel):
    status: Literal["ok", "error"]
    checks: dict[str, ComponentStatus]


# --- Catálogo DCAT-AP (fase 2) ---------------------------------------------------------
# Los campos sin valor en el RDF se devuelven como ``null`` (o lista vacía): licencia,
# contacto, fechas y proyecto son placeholders del prototipo que el frontend muestra tal
# cual. No hay puntuaciones FAIR hasta la fase 4.


class DomainRef(BaseModel):
    """Dominio: concepto ``{BASE_URI}vocab/dominio/{slug}``, el ``dct:subject`` del esquema
    de los temas del dataset (o del propio esquema SKOS)."""

    slug: DomainSlug
    uri: str = Field(description="IRI del concepto de dominio ({BASE_URI}vocab/dominio/{slug})")
    label: str | None = Field(
        description="skos:prefLabel (es) del concepto de dominio, si está cargado"
    )


class ThemeRef(BaseModel):
    uri: str
    label: str | None = Field(description="skos:prefLabel del concepto (es), si está cargado")
    scheme: str | None = Field(description="IRI del esquema (skos:inScheme)")


class AccessRights(BaseModel):
    """``dct:accessRights``. ``code`` es la entrada de la tabla de autoridad de la UE."""

    uri: str
    code: str | None = Field(
        description="Último segmento de la IRI de la tabla europea (PUBLIC, RESTRICTED, "
        "NON_PUBLIC…); null si la IRI no es de esa tabla"
    )


class ResourceRef(BaseModel):
    """Recurso enlazado: IRI (null si es un nodo en blanco) y etiqueta legible."""

    uri: str | None
    label: str | None


class CatalogRef(BaseModel):
    """Catálogo ``{BASE_URI}catalogo/{slug}`` al que pertenece un dataset (decisión 49)."""

    slug: str
    uri: str
    title: str | None


class DatasetCard(BaseModel):
    """Tarjeta de la pantalla Catálogo. Datos de la serie y de su versión actual."""

    slug: str
    uri: str
    title: str | None
    description: str | None
    catalog: CatalogRef | None = Field(
        default=None, description="Catálogo del dataset (decisión 49); null si no está en ninguno"
    )
    domain: DomainRef | None = Field(description="Dominio principal (el primero de domains)")
    domains: list[DomainRef]
    themes: list[ThemeRef]
    access_rights: AccessRights | None
    formats: list[str] = Field(
        description="Tipos de medio IANA (p. ej. text/csv) de las distribuciones de la "
        "versión actual; si una distribución no tiene dcat:mediaType, su dct:title"
    )
    current_version: str | None
    synthetic: bool
    fair_total: float | None = Field(
        default=None,
        description="Puntuación FAIR total (0-100, tal cual la da F-UJI, con sus decimales) "
        "de la última evaluación done de la versión actual; null si no hay",
    )


class DatasetPage(BaseModel):
    items: list[DatasetCard]
    total: int
    page: int
    page_size: int


class VersionSummary(BaseModel):
    """Entrada del historial de versiones (orden: de la más reciente a la más antigua)."""

    version: str | None
    uri: str
    notes: str | None = Field(description="adms:versionNotes")
    issued: str | None
    modified: str | None
    current: bool = Field(description="Es la versión actual (dcat:last)")
    described: bool = Field(
        description="La versión está descrita en el triplestore (false si solo se conoce "
        "por un dcat:previousVersion)"
    )


class VersionRef(BaseModel):
    uri: str
    version: str | None


class DistributionRead(BaseModel):
    uri: str
    title: str | None
    media_type: str | None = Field(description="Tipo de medio IANA, p. ej. text/csv")
    media_type_uri: str | None
    access_url: str | None
    access_rights: AccessRights | None = Field(
        description="De la distribución o, si no tiene, de la versión"
    )
    download: Literal["open", "authenticated", "metadata_only", "unavailable"] = Field(
        default="unavailable",
        description="open: PUBLIC con fichero (cualquiera descarga); authenticated: RESTRICTED "
        "con fichero (miembro o superior); metadata_only: NON_PUBLIC (defensa, nunca hay "
        "fichero); unavailable: sin fichero o accessRights fuera de la tabla europea",
    )
    download_url: str | None = Field(
        default=None,
        description="Ruta del fichero (/dataset/{slug}/{version}/{dist}/fichero, relativa a "
        "la API) cuando download es open o authenticated",
    )
    byte_size: int | None = Field(default=None, description="Tamaño del fichero en bytes")
    sha256: str | None = Field(default=None, description="SHA-256 del fichero (hex)")


class ProvenanceStep(BaseModel):
    """Paso de la cadena PROV-O, ordenada del origen a la actividad que generó la versión."""

    kind: Literal["activity", "entity"]
    uri: str | None = Field(description="null si es un nodo en blanco")
    label: str | None
    agents: list[ResourceRef] = Field(description="prov:wasAssociatedWith (actividades)")


class DcatMetadata(BaseModel):
    publisher: ResourceRef | None
    contact_point: ResourceRef | None
    license: ResourceRef | None
    access_rights: AccessRights | None
    issued: str | None
    modified: str | None
    is_referenced_by: list[ResourceRef]
    themes: list[ThemeRef]
    conforms_to: list[ResourceRef]


FairStatus = Literal["pending", "running", "done", "failed", "not_evaluated"]


class FairSummary(BaseModel):
    """Evaluación FAIR de una versión con F-UJI (decisión 45).

    ``status`` es el de la evaluación más reciente; las puntuaciones, el nivel, el
    evaluador y la fecha son los de la última evaluación ``done`` (pueden convivir: una
    reevaluación en curso muestra la anterior). Todo sale de la respuesta de F-UJI.
    """

    status: FairStatus
    total: float | None = Field(description="summary.score_percent.FAIR de F-UJI (0-100)")
    findable: float | None = Field(description="summary.score_percent.F (0-100)")
    accessible: float | None = Field(description="summary.score_percent.A (0-100)")
    interoperable: float | None = Field(description="summary.score_percent.I (0-100)")
    reusable: float | None = Field(description="summary.score_percent.R (0-100)")
    maturity: str | None = Field(description="summary.maturity.FAIR de F-UJI, tal cual")
    evaluator: str | None = Field(description="F-UJI {software_version} ({metric_version})")
    evaluated_at: str | None = Field(description="Fin de la evaluación (ISO 8601, UTC)")
    report_url: str | None = Field(
        description="Ruta del informe completo (relativa a la API) si hay una evaluación done"
    )


class VersionDetail(BaseModel):
    uri: str
    version: str | None
    title: str | None
    description: str | None
    keywords: list[str]
    version_notes: str | None
    previous_version: VersionRef | None
    in_series: str
    synthetic: bool
    distributions: list[DistributionRead]
    provenance: list[ProvenanceStep]
    metadata: DcatMetadata
    fair: FairSummary | None = Field(default=None, description="Evaluación FAIR (F-UJI)")


class DatasetDetail(BaseModel):
    """Ficha de dataset: la serie, la versión pedida (o la actual) y el historial."""

    slug: str
    uri: str
    title: str | None
    description: str | None
    catalog: CatalogRef | None = Field(
        default=None, description="Catálogo del dataset (decisión 49); null si no está en ninguno"
    )
    publisher: ResourceRef | None = Field(
        default=None,
        description="dct:publisher de la serie (label = su foaf:name; uri = null si es un nodo "
        "en blanco), igual que en el detalle del catálogo. Es lo que edita "
        "PATCH /datasets/{slug} con publisher_name; null si la serie no lo declara",
    )
    synthetic: bool
    domain: DomainRef | None = Field(description="Dominio de la serie (temas de dcat:last)")
    domains: list[DomainRef]
    current_version: str | None
    version: VersionDetail | None = Field(description="null si la serie no tiene versiones")
    versions: list[VersionSummary]


# --- Ingesta -----------------------------------------------------------------------------


class IngestResult(BaseModel):
    slug: str
    uri: str = Field(description="URI de la serie")
    graph: str = Field(description="Grafo con nombre donde se ha guardado")
    versions: list[str]
    triples: int
    created: bool = Field(description="El grafo no existía")
    changed: bool = Field(description="false si el contenido era idéntico al guardado")


class IngestIssue(BaseModel):
    message: str
    focus_node: str | None
    path: str | None
    value: str | None
    severity: str
    source_shape: str | None


class IngestErrorResponse(BaseModel):
    detail: str
    kind: Literal[
        "syntax",
        "structure",
        "uri",
        "shacl",
        "limit",
        "catalog",
        "version_removed",
        "version_immutable",
        "withdrawn",
        "catalog_conflict",
    ] = Field(
        description="limit: se ha superado un límite de la ingesta (tripletas, tamaño "
        "expandido, IRI, profundidad o tiempo o memoria de la validación SHACL). "
        "catalog (422): el catálogo indicado no existe o está dado de baja. "
        "version_removed y version_immutable (409): falta una versión ya publicada o viene "
        "con otro contenido; las versiones afectadas van en issues (focus_node). "
        "withdrawn (409): el slug es de un recurso dado de baja y no se reutiliza. "
        "catalog_conflict (409): la serie ya está en otro catálogo (se mueve con PATCH)"
    )
    issues: list[IngestIssue]
    report: str | None = Field(description="Informe SHACL en texto (solo kind=shacl)")


class ErrorResponse(BaseModel):
    detail: str


# --- Fase 4: ficheros, SPARQL público y consultas guardadas ----------------------------


class DistributionFileRead(BaseModel):
    storage_key: str = Field(description="{slug}/{version}/{dist}")
    byte_size: int
    sha256: str
    media_type: str = Field(description="Del RDF (dcat:mediaType), no del cliente")
    uploaded_at: datetime


class DownloadLink(BaseModel):
    url: str = Field(
        description="Ruta de descarga con el token firmado (?token=…), relativa a la API"
    )
    expires_at: datetime


SAVED_QUERY_MAX_BYTES = 20 * 1024


def _check_text(value: str, *, allow_newlines: bool) -> str:
    for char in value:
        if char in "\n\r\t" and allow_newlines:
            continue
        if has_control_chars(char):
            raise ValueError("no puede contener caracteres de control")
    return value


class SavedQueryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    hint: str | None = Field(default=None, max_length=200)
    query: str = Field(min_length=1, max_length=SAVED_QUERY_MAX_BYTES)

    @field_validator("title", "hint")
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        return None if value is None else _check_text(value, allow_newlines=False)

    @field_validator("query")
    @classmethod
    def _query_text(cls, value: str) -> str:
        if len(value.encode("utf-8")) > SAVED_QUERY_MAX_BYTES:
            raise ValueError("la consulta supera 20 KB")
        return _check_text(value, allow_newlines=True)


class SavedQuery(BaseModel):
    id: str = Field(description="Slug en las de referencia; UUID en las personales")
    title: str
    hint: str | None
    query: str
    kind: Literal["reference", "personal"]
    created_at: str | None
    updated_at: str | None


# --- Vocabularios y ontologías (fase 3) ------------------------------------------------
# Tipos y estados de la pantalla «Vocabularios y ontologías». Los campos sin valor en el
# RDF se devuelven como null o lista vacía. La expresividad DL no se calcula (null).

VocabularyKind = Literal["own", "external", "skos_corp", "skos_domain"]
VocabularyStatus = Literal["published", "draft", "referenced"]
SchemeKind = Literal["skos_corp", "skos_domain", "auxiliary"]


class MetricsSummary(BaseModel):
    """Resumen de métricas de la tarjeta (solo ontologías propias)."""

    classes: int
    properties: int = Field(description="Propiedades de objeto más propiedades de datos")


class VocabularyCard(BaseModel):
    kind: VocabularyKind
    slug: str | None = Field(
        description="Slug de la ontología o del esquema (sin 'corp/'); null en las externas"
    )
    uri: str
    rdf_type: Literal["owl:Ontology", "skos:ConceptScheme"]
    title: str | None
    prefix: str | None = Field(description="vann:preferredNamespacePrefix")
    namespace: str | None = Field(
        description="vann:preferredNamespaceUri o, si falta, {ontología}# / {esquema}/"
    )
    description: str | None
    status: VocabularyStatus
    version: str | None
    metrics: MetricsSummary | None = Field(
        description="Ontologías propias con métricas calculadas; null en el resto"
    )
    concepts: int | None = Field(description="Número de conceptos (solo esquemas)")
    domain: DomainRef | None = Field(
        description="Dominio del esquema de dominio (su dct:subject). null en ontologías "
        "(propias y externas) y en esquemas corporativos: el RDF no les da dominio"
    )
    synthetic: bool


class VocabularyCounts(BaseModel):
    own: int
    external: int
    skos_corp: int
    skos_domain: int


class VocabularyPage(BaseModel):
    items: list[VocabularyCard]
    total: int = Field(description="Tarjetas que cumplen los filtros")
    counts: VocabularyCounts = Field(
        description="Recuento por tipo de todo el repositorio, sin aplicar q, kind ni domain"
    )


class LangLiteral(BaseModel):
    value: str
    lang: str | None = Field(description="Etiqueta de idioma (es, ca, en…); null si no tiene")


class SchemeRef(BaseModel):
    uri: str
    slug: str
    corp: bool
    label: str | None


class ConceptRef(BaseModel):
    uri: str
    label: str | None = Field(description="skos:prefLabel (es) si el concepto está cargado")
    scheme: str | None = Field(description="IRI del esquema (skos:inScheme)")


class SubjectRef(BaseModel):
    """``dct:subject`` de una ontología: un esquema SKOS o un concepto."""

    uri: str
    type: Literal["scheme", "concept", "unknown"]
    label: str | None
    scheme: SchemeRef | None


class OntologyMetricsRead(BaseModel):
    classes: int
    object_properties: int
    data_properties: int
    annotation_properties: int
    individuals: int
    logical_axioms: int = Field(description="Aproximado (ver backend/README.md)")
    imports: int = Field(description="owl:imports declarados (no se descargan)")
    dl_expressivity: None = Field(default=None, description="No se calcula: siempre null")


class OwlProfile(BaseModel):
    name: Literal["OWL 2 DL", "OWL 2 Full"]
    compatible: list[Literal["OWL 2 EL", "OWL 2 QL", "OWL 2 RL"]] = Field(
        description="Perfiles compatibles, aproximados por constructores"
    )
    approximate: bool = True


class ConsistencyRead(BaseModel):
    reasoner: str = Field(description="Siempre 'Pellet'")
    consistent: bool | None = Field(description="null si el razonador no pudo ejecutarse")
    unsatisfiable_classes: int | None
    unsatisfiable: list[str] = Field(description="IRIs de las clases insatisfacibles")
    detail: str | None = Field(description="Motivo si consistent es false o null")
    includes_imports: bool = Field(
        default=False, description="Siempre false: se razona sin las ontologías importadas"
    )


class DocumentationCoverageRead(BaseModel):
    documented: int
    total: int
    percent: float | None = Field(description="% de clases y propiedades con rdfs:comment")
    classes_documented: int
    classes_total: int
    properties_documented: int
    properties_total: int


class ImportRef(BaseModel):
    uri: str
    title: str | None
    prefix: str | None
    version: str | None
    known: bool = Field(description="La ontología importada está descrita en las externas")


class AlignmentMapping(BaseModel):
    source: str
    target: str


class Alignment(BaseModel):
    """Axiomas de la ontología hacia términos de una ontología externa, por relación."""

    target_ontology: str | None = Field(description="null si no se reconoce la ontología")
    title: str | None
    prefix: str | None
    relation: str = Field(description="IRI de la relación (rdfs:subClassOf, skos:exactMatch…)")
    scope: str | None = Field(
        description="rdfs:comment o dct:description de la anotación del axioma, si existe"
    )
    version: str | None = Field(description="owl:versionInfo de la ontología destino")
    count: int
    mappings: list[AlignmentMapping]


class OntologyVersionSummary(BaseModel):
    version: str | None
    version_iri: str
    notes: str | None = Field(description="adms:versionNotes")
    issued: str | None
    current: bool
    described: bool = Field(
        description="false si la versión solo se conoce por un owl:priorVersion"
    )


class OntologyVersionRef(BaseModel):
    version_iri: str
    version: str | None


class OntologyVersioning(BaseModel):
    version: str | None
    version_iri: str
    current_version: str | None
    prior_version: OntologyVersionRef | None
    backward_compatible_with: list[OntologyVersionRef]
    history: list[OntologyVersionSummary]


class OntologyMetadata(BaseModel):
    """Metadatos VANN y DCT de la versión."""

    prefix: str | None
    namespace: str | None
    title: str | None
    description: str | None
    creators: list[ResourceRef]
    contributors: list[ResourceRef]
    publisher: ResourceRef | None
    license: ResourceRef | None
    rights: str | None
    issued: str | None
    modified: str | None
    created: str | None


class DatasetVersionUse(BaseModel):
    version: str | None
    uri: str
    conforms_to: str | None = Field(description="IRI exacta de dct:conformsTo, si aplica")


class DatasetUse(BaseModel):
    slug: str
    uri: str
    title: str | None
    versions: list[DatasetVersionUse]


class OntologyUse(BaseModel):
    slug: str
    uri: str
    title: str | None
    versions: list[str]


class OntologyDetail(BaseModel):
    slug: str
    uri: str
    kind: Literal["own"]
    status: VocabularyStatus
    synthetic: bool
    title: str | None
    description: str | None
    metadata: OntologyMetadata
    versioning: OntologyVersioning
    metrics: OntologyMetricsRead | None = Field(description="null si no se han calculado")
    profile: OwlProfile | None
    consistency: ConsistencyRead | None
    documentation: DocumentationCoverageRead | None
    metrics_computed_at: datetime | None
    metrics_tool: str | None
    imports: list[ImportRef]
    alignments: list[Alignment]
    used_by_datasets: list[DatasetUse] = Field(
        description="Series con alguna versión con dct:conformsTo hacia la ontología o una "
        "de sus versiones"
    )
    subjects: list[SubjectRef] = Field(description="Esquemas SKOS usados (dct:subject)")


class ConceptNode(BaseModel):
    uri: str
    slug: str | None
    label: str | None
    top_concept: bool = Field(description="skos:topConceptOf o skos:hasTopConcept")
    alt_labels: list[LangLiteral] = Field(description="skos:altLabel por idioma")
    children: list[ConceptNode] = Field(description="skos:narrower e inversa de skos:broader")


class SchemeMetadata(BaseModel):
    creators: list[ResourceRef]
    publisher: ResourceRef | None
    license: ResourceRef | None
    issued: str | None
    modified: str | None


class SchemeDetail(BaseModel):
    slug: str
    corp: bool
    kind: SchemeKind = Field(
        description="skos_corp, skos_domain (con dct:subject hacia un dominio) o auxiliary "
        "(vocab/dominio y vocab/tipo-dataset, sin tarjeta en /vocabularies)"
    )
    uri: str
    title: str | None
    description: str | None
    prefix: str | None
    namespace: str | None
    version: str | None
    status: VocabularyStatus
    synthetic: bool
    domain: DomainRef | None = Field(description="Dominio del esquema (dct:subject)")
    responsible: None = Field(
        default=None,
        description="Responsable del esquema: placeholder del prototipo, siempre null hasta "
        "que se decida (decisión abierta 11)",
    )
    metadata: SchemeMetadata
    concept_count: int
    tree: list[ConceptNode] = Field(
        description="Conceptos raíz (los topConcept y los que no tienen broader dentro del "
        "esquema) con sus hijos"
    )


class ConceptUsage(BaseModel):
    datasets: list[DatasetUse] = Field(description="Series con versiones con dcat:theme")
    ontologies: list[OntologyUse] = Field(description="Ontologías con dct:subject")


class ConceptDetail(BaseModel):
    uri: str
    slug: str
    scheme: SchemeRef
    pref_label: str | None = Field(description="skos:prefLabel preferida (es)")
    pref_labels: list[LangLiteral]
    alt_labels: list[LangLiteral]
    definition: str | None
    definitions: list[LangLiteral]
    top_concept: bool
    broader: list[ConceptRef]
    narrower: list[ConceptRef]
    related: list[ConceptRef]
    exact_match: list[str]
    close_match: list[str]
    used_by: ConceptUsage


class OntologyIngestResult(BaseModel):
    slug: str
    uri: str = Field(description="URI de la ontología")
    version: str
    version_iri: str
    graph: str = Field(description="Grafo con nombre (el versionIRI)")
    triples: int
    created: bool
    changed: bool
    metrics_recomputed: bool = Field(
        description="false si la versión ya tenía métricas para el mismo contenido"
    )
    metrics: OntologyMetricsRead
    profile: OwlProfile
    consistency: ConsistencyRead
    documentation: DocumentationCoverageRead


class SchemeIngestResult(BaseModel):
    slug: str
    corp: bool
    uri: str
    graph: str
    concepts: int
    triples: int
    created: bool
    changed: bool


# --- Decisión 49: catálogos, edición de datasets y bajas --------------------------------

TITLE_MAX = 300
DESCRIPTION_MAX = 5000
PUBLISHER_MAX = 300


def _clean_text(value: str | None, *, multiline: bool) -> str | None:
    """Texto de formulario: sin espacios al principio ni al final, no vacío y sin
    caracteres de control (salvo saltos de línea y tabuladores en las descripciones)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("no puede estar vacío")
    allowed = "\n\t" if multiline else ""
    if has_control_chars("".join(c for c in value if c not in allowed)):
        raise ValueError("no puede contener caracteres de control")
    return value


class _FormModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "publisher_name", check_fields=False)
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        return _clean_text(value, multiline=False)

    @field_validator("description", check_fields=False)
    @classmethod
    def _multi_line(cls, value: str | None) -> str | None:
        return _clean_text(value, multiline=True)


def _slug_field() -> Any:
    return Field(
        pattern=SLUG_PATTERN,
        max_length=200,
        description="Slug (minúsculas ASCII, dígitos y guiones; semantic/uris.md). Lo fija "
        "quien crea el recurso y no cambia",
    )


def _title_field(**kwargs: Any) -> Any:
    return Field(
        max_length=TITLE_MAX, description="dct:title (se guarda en español, @es)", **kwargs
    )


def _description_field(**kwargs: Any) -> Any:
    return Field(
        max_length=DESCRIPTION_MAX,
        description="dct:description (se guarda en español, @es)",
        **kwargs,
    )


def _publisher_field(**kwargs: Any) -> Any:
    return Field(
        max_length=PUBLISHER_MAX,
        description="Nombre del publicador (dct:publisher): un agente foaf:Agent con este "
        "foaf:name, sin URI (semantic/uris.md, «Pendiente»)",
        **kwargs,
    )


class CatalogCreate(_FormModel):
    """Alta de un catálogo ``{BASE_URI}catalogo/{slug}``: los campos obligatorios de
    DCAT-AP 3 (forma ``itsh:CatalogShape``)."""

    slug: str = _slug_field()
    title: str = _title_field()
    description: str = _description_field()
    publisher_name: str = _publisher_field()


class CatalogUpdate(_FormModel):
    """Edición de los metadatos de un catálogo: solo cambian los campos presentes."""

    title: str | None = _title_field(default=None)
    description: str | None = _description_field(default=None)
    publisher_name: str | None = _publisher_field(default=None)


class CatalogDatasetRef(BaseModel):
    slug: str
    uri: str
    title: str | None


class CatalogSummary(BaseModel):
    slug: str
    uri: str
    title: str | None
    description: str | None
    publisher: ResourceRef | None
    dataset_count: int = Field(description="Número de datasets (series) del catálogo")


class CatalogPage(BaseModel):
    items: list[CatalogSummary]
    total: int


class CatalogDetail(CatalogSummary):
    datasets: list[CatalogDatasetRef] = Field(description="Series del catálogo, por título")


class DatasetCreate(_FormModel):
    """Alta de un dataset (serie DCAT 3) sin versiones en el catálogo de la ruta. Las
    versiones se publican después con ``POST /datasets`` (RDF)."""

    slug: str = _slug_field()
    title: str = _title_field()
    description: str = _description_field()
    publisher_name: str | None = Field(
        default=None,
        max_length=PUBLISHER_MAX,
        description="Nombre del publicador (opcional en la serie; ver CatalogCreate)",
    )


class DatasetUpdate(_FormModel):
    """Edición de los metadatos de la serie (no de sus versiones, que son inmutables).
    Solo cambian los campos presentes; ``catalog`` mueve el dataset a otro catálogo."""

    title: str | None = _title_field(default=None)
    description: str | None = _description_field(default=None)
    publisher_name: str | None = _publisher_field(default=None)
    catalog: str | None = Field(
        default=None,
        pattern=SLUG_PATTERN,
        max_length=200,
        description="Slug del catálogo de destino (mover el dataset); sus URIs no cambian",
    )


class GoneResponse(BaseModel):
    """410 Gone: ficha mínima de un recurso dado de baja (su lápida)."""

    detail: str
    uri: str = Field(description="URI del recurso dado de baja")
    resource: Literal["catalog", "dataset"] = Field(
        description="Qué era: se deduce de la URI (catalogo/{slug} o dataset/{slug})"
    )
    title: str | None
    withdrawn_at: str | None = Field(description="prov:invalidatedAtTime (xsd:dateTime)")


ConflictKind = Literal["slug_in_use", "withdrawn", "catalog_not_empty"]


class ConflictResponse(BaseModel):
    """409 del CRUD de catálogos y datasets (decisión 49)."""

    detail: str
    kind: ConflictKind = Field(
        description="slug_in_use: ya existe un recurso con ese slug. withdrawn: el slug es de "
        "un recurso dado de baja y no se reutiliza. catalog_not_empty: el catálogo tiene "
        "datasets (en datasets) y no se puede dar de baja"
    )
    datasets: list[str] = Field(
        default_factory=list,
        description="Solo con catalog_not_empty: URIs de las series que siguen en el catálogo",
    )
