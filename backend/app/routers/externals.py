"""Ontologías externas (decisión 51): sustitución entera por una versión nueva, ficha y RDF.

- ``POST /ontologies/externas/{slug}/versions`` (editor; admin hereda): sustituye la
  externa entera. Es la **única** escritura que la API admite sobre una externa.
- ``GET /ontologies/externas/{slug}``: ficha con la referencia, la versión actual y todas
  las versiones, con sus métricas.
- ``GET /ontologies/externas/{slug}/rdf``: RDF de una versión (la actual o ``?version=n``).
- ``PATCH`` y ``DELETE /ontologies/externas/{slug}``: 403 ``not_managed`` (sin edición
  campo a campo y sin baja).

Las rutas van bajo ``/ontologies/externas/`` porque ``externas`` es un slug reservado de las
ontologías propias (``{BASE_URI}onto/externas`` es el grafo de las externas), así que no
chocan con ``/ontologies/{slug}``. Este router se registra antes que el de las propias.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from python_multipart.multipart import MultipartParser, parse_options_header

from app import downloads, external_versions, ingest, schemas
from app.deps import DbDep, SettingsDep, StoreDep, UrisDep
from app.routers.datasets import EditorUser, ingest_error_response
from app.routers.rdf_formats import RDF_RESPONSES, RdfFormatParam, choose_media, graph_response
from app.uris import EXTERNAL_VERSION_PATTERN, SLUG_PATTERN

router = APIRouter(prefix="/ontologies/externas", tags=["ontologies"])

SlugPath = Annotated[
    str,
    Path(
        pattern=SLUG_PATTERN,
        max_length=200,
        description="Slug de la externa: su prefijo VANN (el de su primera sustitución)",
    ),
]
NumberQuery = Annotated[
    str | None,
    Query(
        pattern=EXTERNAL_VERSION_PATTERN,
        max_length=9,
        description="Número de la versión (1, 2, 3…); por defecto, la actual",
    ),
]
MULTIPART_OVERHEAD = 64 * 1024
TEXT_FIELDS = (
    "title",
    "description",
    "version_info",
    "prefix",
    "namespace",
    "publisher",
    "version_notes",
)
MAX_FIELD_BYTES = 16 * 1024
FILE_MEDIA_TYPES: dict[str, ingest.RdfFormat] = {
    "text/turtle": "turtle",
    "application/x-turtle": "turtle",
    "application/ld+json": "json-ld",
}
FILE_EXTENSIONS: dict[str, ingest.RdfFormat] = {
    ".ttl": "turtle",
    ".jsonld": "json-ld",
    ".json": "json-ld",
}
NOT_FOUND = {"model": schemas.ErrorResponse, "description": "La externa (o la versión) no existe"}
UNAVAILABLE = {
    "model": schemas.ErrorResponse,
    "description": "Triplestore no disponible, sin credenciales de escritura o bloqueo de "
    "escritura ocupado",
}
NOT_MANAGED = {
    "model": schemas.ForbiddenResponse,
    "description": "kind=not_managed con cualquier rol: una externa solo se sustituye entera "
    "(POST /ontologies/externas/{slug}/versions); sin rol editor o admin, 403 sin kind",
}


class _Parts:
    """Callbacks de ``MultipartParser``: guarda cada parte (cabeceras y contenido)."""

    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []
        self._field = b""
        self._value = b""

    def callbacks(self) -> dict[str, Any]:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_part_data": self.on_part_data,
        }

    def on_part_begin(self) -> None:
        self.parts.append({"headers": {}, "data": bytearray()})

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]

    def on_header_end(self) -> None:
        self.parts[-1]["headers"][self._field.lower()] = self._value
        self._field, self._value = b"", b""

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        self.parts[-1]["data"] += data[start:end]


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _file_format(content_type: bytes, filename: str) -> ingest.RdfFormat:
    media = content_type.split(b";")[0].strip().lower().decode("latin-1")
    if media in FILE_MEDIA_TYPES:
        return FILE_MEDIA_TYPES[media]
    for extension, rdf_format in FILE_EXTENSIONS.items():
        if filename.lower().endswith(extension):
            return rdf_format
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="El campo 'file' tiene que ser Turtle (text/turtle, .ttl) o JSON-LD "
        "(application/ld+json, .jsonld)",
    )


async def read_external_form(
    request: Request, settings: SettingsDep, _editor: EditorUser
) -> external_versions.ExternalUpload:
    """El ``multipart/form-data`` de la sustitución, con límite de tamaño.

    Depende de ``EditorUser``: autenticación y rol antes de leer un solo byte (como
    ``read_rdf_body``). El cuerpo entero no puede pasar de ``INGEST_MAX_BYTES`` (más un
    margen para las cabeceras del multipart): 413."""
    media, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if media != b"multipart/form-data" or not boundary:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type debe ser multipart/form-data",
        )
    limit = settings.ingest_max_bytes + MULTIPART_OVERHEAD
    too_large = HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Fichero demasiado grande"
    )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    collector = _Parts()
    parser = MultipartParser(boundary, collector.callbacks())
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise too_large
            parser.write(chunk)
        parser.finalize()
    except HTTPException:
        raise
    except Exception as exc:
        raise _bad("multipart/form-data mal formado") from exc

    fields: dict[str, str] = {}
    file: tuple[bytes, ingest.RdfFormat] | None = None
    for part in collector.parts:
        _disposition, params = parse_options_header(
            part["headers"].get(b"content-disposition", b"")
        )
        name = params.get(b"name", b"").decode("latin-1")
        data = bytes(part["data"])
        if name == "file":
            if file is not None:
                raise _bad("Se espera exactamente un campo 'file'")
            if len(data) > settings.ingest_max_bytes:
                raise too_large
            filename = params.get(b"filename", b"").decode("utf-8", "replace")
            file = (data, _file_format(part["headers"].get(b"content-type", b""), filename))
        elif name in TEXT_FIELDS:
            if name in fields:
                raise _bad(f"El campo '{name}' está repetido")
            if len(data) > MAX_FIELD_BYTES:
                raise _bad(f"El campo '{name}' es demasiado largo")
            try:
                fields[name] = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _bad(f"El campo '{name}' tiene que estar en UTF-8") from exc
        else:
            raise _bad(f"Campo no admitido: '{name}'")
    if file is None:
        raise _bad("Se espera exactamente un campo 'file'")
    return external_versions.ExternalUpload(
        data=file[0],
        rdf_format=file[1],
        title=fields.get("title", ""),
        prefix=fields.get("prefix", "").strip(),
        namespace=fields.get("namespace", "").strip(),
        description=fields.get("description"),
        version_info=fields.get("version_info"),
        publisher=fields.get("publisher"),
        version_notes=fields.get("version_notes"),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


FORM_SCHEMA = {
    "type": "object",
    "required": ["file", "title", "prefix", "namespace"],
    "properties": {
        "file": {
            "type": "string",
            "format": "binary",
            "description": "Fichero completo de la ontología, tal como lo publica su "
            "organismo: Turtle (text/turtle, .ttl) o JSON-LD (application/ld+json, .jsonld)",
        },
        "title": {"type": "string", "description": "dct:title en español"},
        "description": {"type": "string", "description": "dct:description en español"},
        "version_info": {
            "type": "string",
            "description": "owl:versionInfo: la versión del publicador (3.2.1, W3C REC). Se "
            "omite si está vacía o es un placeholder como [VERSIÓN]",
        },
        "prefix": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9]*$",
            "description": "vann:preferredNamespacePrefix. En la primera sustitución es el "
            "slug de las versiones, que ya no cambia",
        },
        "namespace": {
            "type": "string",
            "format": "uri",
            "description": "vann:preferredNamespaceUri: sus entidades cuentan como propias "
            "en las métricas",
        },
        "publisher": {"type": "string", "description": "foaf:name del dct:publisher"},
        "version_notes": {"type": "string", "description": "adms:versionNotes en español"},
    },
}


@router.post(
    "/{slug}/versions",
    response_model=schemas.ExternalReplaceResult,
    status_code=status.HTTP_201_CREATED,
    summary="Sustituye entera una ontología externa: crea su versión n+1 (editor o admin)",
    description=(
        "Decisión 51. Recibe en `multipart/form-data` el fichero completo de la ontología "
        "(Turtle o JSON-LD) y sus metadatos de referencia. El fichero tiene que declarar "
        "«<IRI oficial> a owl:Ontology» con la IRI de la externa y no puede describir recursos "
        "bajo BASE_URI; no se valida con las formas. El backend calcula `n` (la última "
        "versión más uno; las sustituciones se serializan), construye el registro de la "
        "versión `{BASE_URI}onto/externas/{slug}/{n}` (`prov:Entity`, `dct:isVersionOf`, "
        "`dcat:version`, `owl:versionInfo`, `prov:generatedAtTime` con la hora del servidor, "
        "`dcat:previousVersion` y `prov:wasRevisionOf` hacia la n-1, `adms:versionNotes`), "
        "valida con SHACL ese registro junto con el de referencia, calcula las métricas OWL "
        "y la consistencia del fichero (owlready2 y Pellet, sin descargar los owl:imports; "
        "cuentan como propias las entidades de `namespace`), escribe el grafo de la versión "
        "(fichero y registro; inmutable) y reescribe solo el registro de esa externa en "
        "`{BASE_URI}onto/externas`, con `dcat:hasVersion` y `dcat:hasCurrentVersion` hacia "
        "la nueva. Robusta ante un fallo a medias: la referencia se reescribe en una sola "
        "petición de Update, y si falla se puede reintentar. "
        "404 si la externa no existe. 422 `syntax` si el fichero no se analiza, `structure` "
        "si un campo no es válido o el fichero no declara la ontología, `uri` si describe "
        "recursos bajo BASE_URI, `shacl` si fallan los registros. 409 `prefix_withdrawn` o "
        "`prefix_in_use` si el prefijo es de otro recurso, dado de baja o vivo (el que una "
        "versión anterior de esta externa dejó de usar sigue siendo suyo); 409 "
        "`version_exists` si la versión `n` ya existe. Auditoría "
        "`external_ontology_replaced`."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": FORM_SCHEMA}},
        }
    },
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": schemas.ErrorResponse,
            "description": "multipart mal formado, sin 'file', con campos repetidos o no admitidos",
        },
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: {
            "model": schemas.ForbiddenResponse,
            "description": "Requiere rol editor o admin",
        },
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "model": schemas.IngestErrorResponse,
            "description": "prefix_withdrawn, prefix_in_use o version_exists",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": schemas.ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": schemas.ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.IngestErrorResponse,
            "description": "Fichero no válido (syntax, structure, uri), campos no válidos "
            "(structure) o informe SHACL de los registros (shacl)",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def replace_external(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    slug: SlugPath,
    upload: Annotated[external_versions.ExternalUpload, Depends(read_external_form)],
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.ExternalReplaceResult | JSONResponse:
    try:
        result = external_versions.replace_external(
            store, db, uris, settings, slug, upload, actor=editor
        )
    except external_versions.ExternalNotFoundError as exc:
        raise _not_found() from exc
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    parts = external_versions.metrics_parts(result.metrics, result.consistency)
    return schemas.ExternalReplaceResult(
        slug=result.slug,
        uri=result.uri,
        number=result.number,
        version=str(result.number),
        version_uri=result.version_uri,
        graph=result.version_uri,
        previous_version=result.previous_version,
        generated_at=result.generated_at,
        triples=result.triples,
        **parts,
    )


@router.get(
    "/{slug}",
    response_model=schemas.ExternalOntologyDetail,
    summary="Ficha de una ontología externa: referencia, versión actual y versiones",
    description="Decisión 51. La referencia de `{BASE_URI}onto/externas`, la versión actual "
    "(`dcat:hasCurrentVersion`) y todas las versiones, de la más reciente a la más antigua, "
    "con sus métricas. Una externa que nunca se ha sustituido no tiene versiones ni métricas.",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def get_external(
    slug: SlugPath, store: StoreDep, db: DbDep, uris: UrisDep
) -> schemas.ExternalOntologyDetail:
    try:
        return external_versions.get_external(store, db, uris, slug)
    except external_versions.ExternalNotFoundError as exc:
        raise _not_found() from exc


@router.get(
    "/{slug}/rdf",
    summary="RDF de una versión de ontología externa: Turtle, RDF/XML o JSON-LD",
    description="El grafo de la versión (fichero oficial y registro de la versión): la "
    "actual o `?version=n`. Formato por `?format=` o, si no se indica, por `Accept`. 404 si "
    "la externa no tiene versiones.",
    response_class=Response,
    responses=RDF_RESPONSES,
)
def get_external_rdf(
    request: Request,
    slug: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    version: NumberQuery = None,
    rdf_format: Annotated[RdfFormatParam | None, Query(alias="format")] = None,
    download: downloads.DownloadQuery = False,
) -> Response:
    media = choose_media(request, rdf_format)
    try:
        if version is None:
            info = external_versions.find_external(
                external_versions.reference_graph(store, uris), uris, slug
            )
            if not info.versions:
                raise external_versions.ExternalNotFoundError(slug)
            number = info.last
        else:
            number = int(version)
        graph = external_versions.version_rdf(store, uris, slug, number)
    except external_versions.ExternalNotFoundError as exc:
        raise _not_found() from exc
    return downloads.apply(
        graph_response(graph, uris, media), download, [f"externa-{slug}", str(number)], media
    )


def _forbidden() -> JSONResponse:
    body = schemas.ForbiddenResponse(
        detail="Una ontología externa no se edita campo a campo ni se da de baja: solo se "
        "sustituye entera (POST /ontologies/externas/{slug}/versions)",
        kind="not_managed",
    )
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=body.model_dump())


@router.patch(
    "/{slug}",
    summary="No admitido: una ontología externa no se edita campo a campo",
    description="Siempre 403 `not_managed` (decisión 51): sus metadatos llegan con la "
    "sustitución entera.",
    status_code=status.HTTP_403_FORBIDDEN,
    response_model=schemas.ForbiddenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: NOT_MANAGED,
    },
)
def update_external(_editor: EditorUser, slug: SlugPath) -> JSONResponse:
    return _forbidden()


@router.delete(
    "/{slug}",
    summary="No admitido: una ontología externa no se da de baja",
    description="Siempre 403 `not_managed` (decisión 51): ni la externa ni sus versiones se "
    "dan de baja.",
    status_code=status.HTTP_403_FORBIDDEN,
    response_model=schemas.ForbiddenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: NOT_MANAGED,
    },
)
def withdraw_external(_editor: EditorUser, slug: SlugPath) -> JSONResponse:
    return _forbidden()
