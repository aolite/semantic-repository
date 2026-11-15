"""Catálogo de datasets: lectura pública (lector anónimo) e ingesta (editor; admin hereda).

En la fase 2 solo hay metadatos: ninguna ruta sirve el contenido de las distribuciones.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from rdflib import Graph, URIRef

from app import catalog, downloads, ingest, schemas
from app.deps import DbDep, SettingsDep, StoreDep, UrisDep, require_role
from app.models import Role, User
from app.negotiation import JSONLD, TURTLE, negotiate
from app.uris import DCAT, SLUG_PATTERN, VERSION_PATTERN, DomainSlug

router = APIRouter(prefix="/datasets", tags=["datasets"])

EditorUser = Annotated[User, Depends(require_role(Role.EDITOR))]  # admin hereda de editor
SlugPath = Annotated[
    str,
    Path(pattern=SLUG_PATTERN, max_length=200, description="Slug de la serie (semantic/uris.md)"),
]
VersionQuery = Annotated[
    str | None,
    Query(pattern=VERSION_PATTERN, max_length=50, description="Versión MAYOR.MENOR.PARCHE"),
]

INGEST_MEDIA_TYPES: dict[str, ingest.RdfFormat] = {
    TURTLE: "turtle",
    JSONLD: "json-ld",
}

RDF_BODY_SCHEMA = {"type": "string", "description": "RDF serializado"}
NOT_FOUND = {"model": schemas.ErrorResponse, "description": "La serie o la versión no existe"}


async def read_rdf_body(
    request: Request, settings: SettingsDep, _editor: EditorUser
) -> tuple[bytes, ingest.RdfFormat]:
    """Lee el cuerpo con límite de tamaño y deduce el formato de ``Content-Type``.

    Depende de ``EditorUser``: autenticación y rol se comprueban **antes** de mirar el
    ``Content-Type`` o leer un solo byte del cuerpo (QA-G2-03). Un anónimo recibe 401 y
    un miembro 403, sin que el servidor lea hasta ``INGEST_MAX_BYTES``.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    rdf_format = INGEST_MEDIA_TYPES.get(content_type)
    if rdf_format is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type debe ser text/turtle o application/ld+json",
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.ingest_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="RDF demasiado grande"
        )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > settings.ingest_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="RDF demasiado grande"
            )
        chunks.append(chunk)
    return b"".join(chunks), rdf_format


def ingest_error_response(exc: ingest.IngestError) -> JSONResponse:
    body = schemas.IngestErrorResponse(
        detail=exc.detail,
        kind=exc.kind,
        issues=[schemas.IngestIssue(**issue.__dict__) for issue in exc.issues],
        report=exc.report,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=body.model_dump()
    )


@router.post(
    "",
    response_model=schemas.IngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Publica una serie de dataset (con sus versiones) validada con SHACL",
    description=(
        "Recibe la serie completa (dcat:DatasetSeries con sus dcat:Dataset y "
        "dcat:Distribution) en Turtle o JSON-LD; las IRIs relativas se resuelven contra "
        "BASE_URI. Sustituye por completo el grafo con nombre `{BASE_URI}dataset/{slug}`. "
        "201 si la serie es nueva; 200 si ya existía (con `changed=false` si el contenido era "
        "idéntico). Requiere rol editor (admin hereda los permisos de editor)."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                TURTLE: {"schema": RDF_BODY_SCHEMA},
                JSONLD: {"schema": RDF_BODY_SCHEMA},
            },
        }
    },
    responses={
        status.HTTP_200_OK: {"model": schemas.IngestResult, "description": "Serie sustituida"},
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: {"description": "Requiere rol editor o admin"},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": schemas.ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": schemas.ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.IngestErrorResponse,
            "description": "RDF no válido: sintaxis, estructura, URIs o informe SHACL",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": schemas.ErrorResponse,
            "description": "Triplestore no disponible o sin credenciales de escritura",
        },
    },
)
def create_dataset(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    body: Annotated[tuple[bytes, ingest.RdfFormat], Depends(read_rdf_body)],
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
    response: Response,
) -> schemas.IngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(data, rdf_format, uris.base)
        prepared = ingest.prepare_series(graph, uris, settings.semantic_dir)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    result = ingest.publish_and_audit(store, db, prepared, actor=editor, via="api")
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return schemas.IngestResult(
        slug=result.slug,
        uri=result.uri,
        graph=result.graph_uri,
        versions=result.versions,
        triples=result.triples,
        created=result.created,
        changed=result.changed,
    )


@router.get(
    "",
    response_model=schemas.DatasetPage,
    summary="Tarjetas del catálogo (lector anónimo)",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse}},
)
def list_datasets(
    store: StoreDep,
    uris: UrisDep,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Texto en título, descripción y temas (sin distinguir mayúsculas ni "
            "acentos)",
        ),
    ] = None,
    domain: Annotated[DomainSlug | None, Query(description="Slug del dominio")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> schemas.DatasetPage:
    return catalog.list_datasets(store, uris, q=q, domain=domain, page=page, page_size=page_size)


@router.get(
    "/{slug}",
    response_model=schemas.DatasetDetail,
    summary="Ficha de dataset: serie, versión actual (o ?version=) e historial",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def get_dataset(
    slug: SlugPath, store: StoreDep, uris: UrisDep, version: VersionQuery = None
) -> schemas.DatasetDetail:
    try:
        return catalog.get_dataset(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc


RDF_RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF de la versión",
        "content": {TURTLE: {"schema": RDF_BODY_SCHEMA}, JSONLD: {"schema": RDF_BODY_SCHEMA}},
    },
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}

FORMAT_TO_MEDIA = {"turtle": TURTLE, "jsonld": JSONLD}


def rdf_response(graph_text: str, media: str) -> Response:
    return Response(
        content=graph_text,
        media_type=media,
        headers={"Vary": "Accept"},
    )


@router.get(
    "/{slug}/rdf",
    summary="RDF de la versión (pestaña «Descripción RDF»): Turtle o JSON-LD",
    description="Formato por `?format=` o, si no se indica, por la cabecera `Accept`.",
    response_class=Response,
    responses=RDF_RESPONSES,
)
def get_dataset_rdf(
    request: Request,
    slug: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    version: VersionQuery = None,
    rdf_format: Annotated[Literal["turtle", "jsonld"] | None, Query(alias="format")] = None,
    download: downloads.DownloadQuery = False,
) -> Response:
    if rdf_format is not None:
        media: str | None = FORMAT_TO_MEDIA[rdf_format]
    else:
        media = negotiate(request.headers.get("accept"), [TURTLE, JSONLD])
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Formatos disponibles: text/turtle, application/ld+json",
        )
    try:
        graph = catalog.version_rdf(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    text = catalog.serialize(graph, uris, "json-ld" if media == JSONLD else "turtle")
    number = version or _version_in(graph, uris.series(slug))
    return downloads.apply(rdf_response(text, media), download, [slug, number], media)


def _version_in(graph: Graph, series_uri: str) -> str | None:
    """``dcat:version`` de la versión que contiene el grafo (la actual si no se pidió)."""
    for node in graph.subjects(DCAT.inSeries, URIRef(series_uri)):
        value = graph.value(node, DCAT.version)
        if value is not None:
            return str(value)
    return None
