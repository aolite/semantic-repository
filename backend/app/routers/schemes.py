"""Esquemas SKOS: ingesta, edición y baja (editor; admin hereda) y lectura pública.

Rutas: los esquemas de dominio en ``/schemes/{slug}`` y los corporativos en
``/schemes/corp/{slug}``, igual que sus URIs (``{BASE_URI}vocab/{slug}`` y
``{BASE_URI}vocab/corp/{slug}``). ``corp`` es un slug reservado: no hay esquema de dominio
con ese nombre. Las rutas ``corp/`` se declaran primero para que tengan prioridad.

Decisión 50: cada esquema está en un catálogo (``?catalog={slug}`` al publicarlo), se
edita (metadatos y catálogo) y se da de baja con lápida y 410 (también sus conceptos, por
el prefijo). Los auxiliares (``vocab/dominio``, ``vocab/tipo-dataset``) no se gestionan
desde la aplicación: 403 ``not_managed``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from rdflib import URIRef
from rdflib.namespace import OWL

from app import (
    catalog,
    catalogs,
    downloads,
    ingest,
    schemas,
    vocab_crud,
    vocab_ingest,
    vocabularies,
)
from app.deps import DbDep, SettingsDep, StoreDep, UrisDep
from app.negotiation import JSONLD, TURTLE
from app.routers.catalogs import crud_error_response
from app.routers.datasets import (
    RDF_BODY_SCHEMA,
    EditorUser,
    ingest_error_response,
    read_rdf_body,
)
from app.routers.gone import GONE, raise_if_gone
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
    status.HTTP_410_GONE: GONE,
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}
CatalogQuery = Annotated[
    str | None,
    Query(
        alias="catalog",
        pattern=SLUG_PATTERN,
        max_length=200,
        description="Catálogo del esquema (catalogo/{slug}, decisión 50): el backend añade "
        "«<catálogo> dcat:resource <esquema>» antes de validar (si el RDF ya declara otro, "
        "422). Hace falta si el RDF no lo declara",
    ),
]
FORBIDDEN = {
    "model": schemas.ForbiddenResponse,
    "description": "Requiere rol editor o admin; o kind=not_managed: un esquema auxiliar "
    "(vocab/dominio, vocab/tipo-dataset) no se gestiona desde la aplicación",
}
UNAVAILABLE = {
    "model": schemas.ErrorResponse,
    "description": "Triplestore no disponible o sin credenciales de escritura",
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
        "JSON-LD; las IRIs relativas se resuelven contra BASE_URI (también sirve para "
        "«Importar SKOS»). Sustituye por completo el grafo con nombre del esquema. "
        "Decisión 50: el esquema pertenece a un catálogo (`?catalog={slug}` o el triple "
        "«<catálogo> dcat:resource <esquema>» en el RDF), que se guarda en el grafo del "
        "catálogo. 409 `catalog_conflict` si ya está en otro catálogo (se mueve con PATCH), "
        "`withdrawn` si se dio de baja, `prefix_withdrawn` si su prefijo VANN era de un "
        "recurso dado de baja, `prefix_in_use` si lo usa otro esquema, otra ontología "
        "externa o alguna versión publicada de otra ontología propia, `concepts_removed` si faltan conceptos ya publicados (un "
        "concepto se retira con owl:deprecated true) y `concept_reactivated` si un concepto "
        "retirado deja de estarlo; 422 `catalog` si el catálogo no existe y `replacement` si "
        "un sustituto (dct:isReplacedBy) no es un concepto vivo; 403 `not_managed` con un "
        "esquema auxiliar. 201 si es nuevo; 200 si ya existía (`changed=false` si era "
        "idéntico). Requiere rol editor (admin hereda los permisos de editor)."
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
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_409_CONFLICT: {
            "model": schemas.IngestErrorResponse,
            "description": "catalog_conflict, withdrawn, prefix_withdrawn, prefix_in_use, "
            "concepts_removed o concept_reactivated",
        },
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
    catalog_slug: CatalogQuery = None,
) -> schemas.SchemeIngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(
            data, rdf_format, uris.base, max_triples=settings.ingest_max_triples
        )
        if catalog_slug is not None:
            graph = vocab_ingest.add_resource_membership(graph, uris, catalog_slug)
        prepared = vocab_ingest.prepare_scheme(graph, uris, settings)
        result = vocab_ingest.publish_scheme_and_audit(store, db, prepared, actor=editor, via="api")
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
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
        catalog=result.catalog_uri,
    )


# --- Decisión 50: edición y baja ---------------------------------------------------------

EDIT_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": schemas.ErrorResponse, "description": "No autenticado"},
    status.HTTP_403_FORBIDDEN: FORBIDDEN,
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_410_GONE: GONE,
    status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
}
PATCH_DESCRIPTION = (
    "Cambia solo los campos presentes: título (dct:title y skos:prefLabel en español), "
    "descripción y publicador del esquema y, con `catalog`, lo mueve a otro catálogo (se "
    "quita del de origen y se añade al de destino; ninguna URI cambia). Sus conceptos no "
    "cambian: se cambian republicando el esquema con `POST /schemes`. El resultado se valida "
    "con SHACL. 422 `catalog` si el catálogo de destino no existe o está dado de baja; 403 "
    "`not_managed` con un esquema auxiliar."
)
DELETE_DESCRIPTION = (
    "Borrado lógico (decisión 50): el esquema y sus conceptos salen de su catálogo, de los "
    "listados y de SPARQL; su URI y las de sus conceptos responden 410 con una ficha mínima. "
    "Su slug y su prefijo VANN no se reutilizan. 409 `in_use` si lo usan recursos vivos "
    "(un concepto suyo como `dcat:theme` de una versión de dataset, `dct:subject` de una "
    "versión de ontología hacia un concepto suyo o hacia el esquema, o un concepto suyo como "
    "destino de `skos:related`/`*Match`/`dct:isReplacedBy` desde otro esquema), con los usos "
    "en `used_by`. 403 `not_managed` con un esquema auxiliar. Robusta ante un fallo a medias: "
    "lo del triplestore va en una sola petición de Update; si falla (503), se reintenta."
)
CONFLICT_IN_USE = {
    "model": schemas.ConflictResponse,
    "description": "Lo usan recursos vivos (kind=in_use, con used_by)",
}
INVALID_EDIT = {
    "model": schemas.IngestErrorResponse,
    "description": "Cuerpo no válido, catálogo de destino inexistente o informe SHACL",
}


def _update(
    editor: EditorUser,
    slug: str,
    corp: bool,
    data: schemas.SchemeUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.SchemeDetail | JSONResponse:
    try:
        vocab_crud.update_scheme(store, db, uris, settings, slug, corp, data, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return _scheme(store, uris, slug, corp)


def _withdraw(
    editor: EditorUser,
    slug: str,
    corp: bool,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    try:
        vocab_crud.withdraw_scheme(store, db, uris, settings, slug, corp, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/corp/{slug}",
    response_model=schemas.SchemeDetail,
    summary="Edita un esquema corporativo y lo mueve de catálogo (editor o admin)",
    description=PATCH_DESCRIPTION,
    responses={**EDIT_RESPONSES, status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_EDIT},
)
def update_corp_scheme(
    editor: EditorUser,
    slug: SlugPath,
    data: schemas.SchemeUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.SchemeDetail | JSONResponse:
    return _update(editor, slug, True, data, db, store, uris, settings)


@router.delete(
    "/corp/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Da de baja un esquema corporativo (editor o admin)",
    description=DELETE_DESCRIPTION,
    responses={**EDIT_RESPONSES, status.HTTP_409_CONFLICT: CONFLICT_IN_USE},
)
def withdraw_corp_scheme(
    editor: EditorUser,
    slug: SlugPath,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    return _withdraw(editor, slug, True, db, store, uris, settings)


@router.patch(
    "/{slug}",
    response_model=schemas.SchemeDetail,
    summary="Edita un esquema de dominio y lo mueve de catálogo (editor o admin)",
    description=PATCH_DESCRIPTION,
    responses={**EDIT_RESPONSES, status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_EDIT},
)
def update_scheme(
    editor: EditorUser,
    slug: SlugPath,
    data: schemas.SchemeUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.SchemeDetail | JSONResponse:
    return _update(editor, slug, False, data, db, store, uris, settings)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Da de baja un esquema de dominio (editor o admin)",
    description=DELETE_DESCRIPTION,
    responses={**EDIT_RESPONSES, status.HTTP_409_CONFLICT: CONFLICT_IN_USE},
)
def withdraw_scheme(
    editor: EditorUser,
    slug: SlugPath,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    return _withdraw(editor, slug, False, db, store, uris, settings)


# --- Lectura -----------------------------------------------------------------------------


def _gone_or_not_found(store: StoreDep, uris: UrisDep, slug: str, corp: bool) -> HTTPException:
    """410 si el esquema se dio de baja (también para sus conceptos, por el prefijo)."""
    uri = uris.scheme(slug, corp=corp)
    if uris.scheme_parts(uri) == (slug, corp):
        raise_if_gone(store, uris, uri)
    return _not_found()


def _scheme(store: StoreDep, uris: UrisDep, slug: str, corp: bool) -> schemas.SchemeDetail:
    try:
        return vocabularies.get_scheme(store, uris, slug, corp)
    except catalog.NotFoundError as exc:
        raise _gone_or_not_found(store, uris, slug, corp) from exc


def _concept(
    store: StoreDep, uris: UrisDep, slug: str, corp: bool, concept: str
) -> schemas.ConceptDetail:
    try:
        return vocabularies.get_concept(store, uris, slug, corp, concept)
    except catalog.NotFoundError as exc:
        raise _gone_or_not_found(store, uris, slug, corp) from exc


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
        raise _gone_or_not_found(store, uris, slug, corp) from exc
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
