"""Esquemas SKOS: ingesta (editor; admin hereda) y lectura pública.

Rutas: los esquemas de dominio en ``/schemes/{slug}`` y los corporativos en
``/schemes/corp/{slug}``, igual que sus URIs (``{BASE_URI}vocab/{slug}`` y
``{BASE_URI}vocab/corp/{slug}``). ``corp`` es un slug reservado: no hay esquema de dominio
con ese nombre. Las rutas ``corp/`` se declaran primero para que tengan prioridad.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from rdflib import URIRef
from rdflib.namespace import OWL

from app import catalog, downloads, ingest, schemas, vocab_ingest, vocabularies
from app.deps import DbDep, SettingsDep, StoreDep, UrisDep
from app.negotiation import JSONLD, TURTLE
from app.routers.datasets import (
    RDF_BODY_SCHEMA,
    EditorUser,
    ingest_error_response,
    read_rdf_body,
)
from app.routers.rdf_formats import RDF_RESPONSES, RdfFormatParam, choose_media, graph_response
from app.uris import SLUG_PATTERN

router = APIRouter(prefix="/schemes", tags=["schemes"])

SlugPath = Annotated[
    str, Path(pattern=SLUG_PATTERN, max_length=200, description="Slug del esquema")
]
ConceptPath = Annotated[
    str, Path(pattern=SLUG_PATTERN, max_length=200, description="Slug del concepto")
]
FormatQuery = Annotated[RdfFormatParam | None, Query(alias="format")]
NOT_FOUND = {"model": schemas.ErrorResponse, "description": "El esquema o el concepto no existe"}
READ_RESPONSES = {
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


@router.post(
    "",
    response_model=schemas.SchemeIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Publica un esquema SKOS validado con SHACL",
    description=(
        "Recibe un skos:ConceptScheme (`{BASE_URI}vocab/{slug}` o "
        "`{BASE_URI}vocab/corp/{slug}`) con sus conceptos (`{esquema}/{slug}`) en Turtle o "
        "JSON-LD; las IRIs relativas se resuelven contra BASE_URI. Sustituye por completo el "
        "grafo con nombre del esquema. 201 si es nuevo; 200 si ya existía (`changed=false` si "
        "era idéntico). Requiere rol editor (admin hereda los permisos de editor)."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {TURTLE: {"schema": RDF_BODY_SCHEMA}, JSONLD: {"schema": RDF_BODY_SCHEMA}},
        }
    },
    responses={
        status.HTTP_200_OK: {"model": schemas.SchemeIngestResult, "description": "Sustituido"},
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
def create_scheme(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    body: Annotated[tuple[bytes, ingest.RdfFormat], Depends(read_rdf_body)],
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
    response: Response,
) -> schemas.SchemeIngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(data, rdf_format, uris.base)
        prepared = vocab_ingest.prepare_scheme(graph, uris, settings)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    result = vocab_ingest.publish_scheme_and_audit(store, db, prepared, actor=editor, via="api")
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return schemas.SchemeIngestResult(
        slug=result.slug,
        corp=result.corp,
        uri=result.uri,
        graph=result.graph_uri,
        concepts=result.concepts,
        triples=result.triples,
        created=result.created,
        changed=result.changed,
    )


# --- Lectura -----------------------------------------------------------------------------


def _scheme(store: StoreDep, uris: UrisDep, slug: str, corp: bool) -> schemas.SchemeDetail:
    try:
        return vocabularies.get_scheme(store, uris, slug, corp)
    except catalog.NotFoundError as exc:
        raise _not_found() from exc


def _concept(
    store: StoreDep, uris: UrisDep, slug: str, corp: bool, concept: str
) -> schemas.ConceptDetail:
    try:
        return vocabularies.get_concept(store, uris, slug, corp, concept)
    except catalog.NotFoundError as exc:
        raise _not_found() from exc


def _rdf(
    request: Request,
    store: StoreDep,
    uris: UrisDep,
    slug: str,
    corp: bool,
    fmt: RdfFormatParam | None,
    download: bool,
) -> Response:
    media = choose_media(request, fmt)
    try:
        graph = vocabularies.scheme_rdf(store, uris, slug, corp)
    except catalog.NotFoundError as exc:
        raise _not_found() from exc
    version = graph.value(URIRef(uris.scheme(slug, corp=corp)), OWL.versionInfo)
    parts = ["corp" if corp else None, slug, str(version) if version is not None else None]
    return downloads.apply(graph_response(graph, uris, media), download, parts, media)


@router.get(
    "/corp/{slug}",
    response_model=schemas.SchemeDetail,
    summary="Esquema SKOS corporativo: metadatos, dominio y árbol de conceptos",
    responses=READ_RESPONSES,
)
def get_corp_scheme(slug: SlugPath, store: StoreDep, uris: UrisDep) -> schemas.SchemeDetail:
    return _scheme(store, uris, slug, True)


@router.get(
    "/corp/{slug}/rdf",
    summary="RDF de un esquema corporativo",
    response_class=Response,
    responses=RDF_RESPONSES,
)
def get_corp_scheme_rdf(
    request: Request,
    slug: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    fmt: FormatQuery = None,
    download: downloads.DownloadQuery = False,
) -> Response:
    return _rdf(request, store, uris, slug, True, fmt, download)


@router.get(
    "/corp/{slug}/concepts/{concept}",
    response_model=schemas.ConceptDetail,
    summary="Concepto de un esquema corporativo",
    responses=READ_RESPONSES,
)
def get_corp_concept(
    slug: SlugPath, concept: ConceptPath, store: StoreDep, uris: UrisDep
) -> schemas.ConceptDetail:
    return _concept(store, uris, slug, True, concept)


@router.get(
    "/{slug}",
    response_model=schemas.SchemeDetail,
    summary="Esquema SKOS de dominio: metadatos, dominio y árbol de conceptos",
    responses=READ_RESPONSES,
)
def get_scheme(slug: SlugPath, store: StoreDep, uris: UrisDep) -> schemas.SchemeDetail:
    return _scheme(store, uris, slug, False)


@router.get(
    "/{slug}/rdf",
    summary="RDF de un esquema de dominio",
    response_class=Response,
    responses=RDF_RESPONSES,
)
def get_scheme_rdf(
    request: Request,
    slug: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    fmt: FormatQuery = None,
    download: downloads.DownloadQuery = False,
) -> Response:
    return _rdf(request, store, uris, slug, False, fmt, download)


@router.get(
    "/{slug}/concepts/{concept}",
    response_model=schemas.ConceptDetail,
    summary="Concepto: etiquetas por idioma, jerarquía, mapeos y recursos que lo usan",
    responses=READ_RESPONSES,
)
def get_concept(
    slug: SlugPath, concept: ConceptPath, store: StoreDep, uris: UrisDep
) -> schemas.ConceptDetail:
    return _concept(store, uris, slug, False, concept)
