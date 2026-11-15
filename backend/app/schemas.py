"""Esquemas Pydantic de entrada y salida de la API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Role
from app.security import PASSWORD_MIN_LENGTH, has_control_chars
from app.uris import DomainSlug

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
    """Dominio del dataset: esquema SKOS ``{BASE_URI}vocab/{slug}`` de sus temas."""

    slug: DomainSlug
    uri: str
    label: str | None = Field(description="skos:prefLabel del esquema (es), si está cargado")


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


class DatasetCard(BaseModel):
    """Tarjeta de la pantalla Catálogo. Datos de la serie y de su versión actual."""

    slug: str
    uri: str
    title: str | None
    description: str | None
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


class DatasetDetail(BaseModel):
    """Ficha de dataset: la serie, la versión pedida (o la actual) y el historial."""

    slug: str
    uri: str
    title: str | None
    description: str | None
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
    kind: Literal["syntax", "structure", "uri", "shacl"]
    issues: list[IngestIssue]
    report: str | None = Field(description="Informe SHACL en texto (solo kind=shacl)")


class ErrorResponse(BaseModel):
    detail: str
