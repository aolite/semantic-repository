"""Catálogo de datasets: lectura pública (lector anónimo) e ingesta (editor; admin hereda).

Decisión 49: cada serie pertenece a un catálogo. ``POST /datasets`` (RDF) exige el triple
de pertenencia o ``?catalog={slug}``; ``PATCH /datasets/{slug}`` edita los metadatos de
la serie (y la mueve de catálogo); ``DELETE /datasets/{slug}`` la da de baja. Un dataset
dado de baja responde 410 con su ficha mínima. Los datasets se crean sin versiones con
``POST /catalogs/{slug}/datasets`` (``app.routers.catalogs``).

Los ficheros de distribución y la evaluación FAIR (fase 4) están en
``app.routers.dataset_files``; el fichero en sí se sirve en
``/dataset/{slug}/{version}/{dist}/fichero`` (``app.routers.linked_data``).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from rdflib import Graph, URIRef

from app import catalog, catalogs, downloads, fair_views, ingest, schemas
from app.deps import DbDep, SettingsDep, StorageDep, StoreDep, UrisDep, require_role
from app.models import Role, User
from app.negotiation import JSONLD, TURTLE, negotiate
from app.routers.gone import GONE, gone_json, raise_if_series_gone
from app.storage import StorageError
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
CatalogQuery = Annotated[
    str | None,
    Query(
        pattern=SLUG_PATTERN,
        max_length=200,
        description="Slug del catálogo (catalogo/{slug})",
    ),
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
    code = (
        status.HTTP_409_CONFLICT
        if exc.kind in ingest.CONFLICT_KINDS
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return JSONResponse(status_code=code, content=body.model_dump())


@router.post(
    "",
    response_model=schemas.IngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Publica una serie de dataset (con sus versiones) validada con SHACL",
    description=(
        "Recibe la serie completa (dcat:DatasetSeries con sus dcat:Dataset y "
        "dcat:Distribution) en Turtle o JSON-LD; las IRIs relativas se resuelven contra "
        "BASE_URI. Sustituye por completo el grafo con nombre `{BASE_URI}dataset/{slug}`. "
        "Decisión 49: el RDF lleva exactamente un `<{BASE_URI}catalogo/{slug}> dcat:dataset "
        "<serie>` (o se indica `?catalog={slug}` y el backend lo añade antes de validar); "
        "se guarda en el grafo del catálogo. 422 `catalog` si el catálogo no existe o está "
        "dado de baja; 409 `catalog_conflict` si la serie ya está en otro catálogo (se "
        "mueve con PATCH) y 409 `withdrawn` si el slug es de un dataset dado de baja. "
        "Las versiones ya publicadas son inmutables: tienen que venir todas y con el mismo "
        "contenido (409 `version_removed` o `version_immutable`, con las versiones en "
        "`issues`). Las versiones nuevas se encolan para evaluarlas con F-UJI en segundo "
        "plano. 201 si la serie es nueva; 200 si ya existía (con `changed=false` si el "
        "contenido era idéntico). Requiere rol editor (admin hereda los permisos de editor)."
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
        status.HTTP_409_CONFLICT: {
            "model": schemas.IngestErrorResponse,
            "description": "Versión publicada ausente (version_removed) o con otro contenido "
            "(version_immutable), serie en otro catálogo (catalog_conflict) o slug dado de "
            "baja (withdrawn)",
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
def create_dataset(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    body: Annotated[tuple[bytes, ingest.RdfFormat], Depends(read_rdf_body)],
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
    response: Response,
    catalog_slug: Annotated[
        str | None,
        Query(
            alias="catalog",
            pattern=SLUG_PATTERN,
            max_length=200,
            description="Catálogo de la serie: el backend añade el triple de pertenencia "
            "antes de validar (si el RDF ya declara otro, 422)",
        ),
    ] = None,
) -> schemas.IngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(
            data, rdf_format, uris.base, max_triples=settings.ingest_max_triples
        )
        if catalog_slug is not None:
            graph = ingest.add_membership(graph, uris, catalog_slug)
        prepared = ingest.prepare_series(graph, uris, settings.semantic_dir)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    try:
        result = ingest.publish_and_audit(store, db, prepared, actor=editor, via="api")
    except ingest.IngestError as exc:  # 409: versiones inmutables, catálogo, baja
        return ingest_error_response(exc)
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
    db: DbDep,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Texto en título, descripción, temas o URI de la serie (subcadena, "
            "sin distinguir mayúsculas ni acentos)",
        ),
    ] = None,
    domain: Annotated[DomainSlug | None, Query(description="Slug del dominio")] = None,
    catalog_slug: Annotated[
        str | None,
        Query(
            alias="catalog",
            pattern=SLUG_PATTERN,
            max_length=200,
            description="Solo los datasets de este catálogo (catalogo/{slug})",
        ),
    ] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> schemas.DatasetPage:
    result = catalog.list_datasets(
        store, uris, q=q, domain=domain, catalog=catalog_slug, page=page, page_size=page_size
    )
    fair_views.add_fair_totals(db, uris, result.items)
    return result


@router.get(
    "/{slug}",
    response_model=schemas.DatasetDetail,
    summary="Ficha de dataset: serie, versión actual (o ?version=) e historial",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_410_GONE: GONE,
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def get_dataset(
    slug: SlugPath, store: StoreDep, uris: UrisDep, db: DbDep, version: VersionQuery = None
) -> schemas.DatasetDetail:
    try:
        detail = catalog.get_dataset(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise_if_series_gone(store, uris, slug)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    if detail.version is not None:
        fair_views.enrich_version(db, uris, slug, detail.version)
    return detail


RDF_RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF de la versión",
        "content": {TURTLE: {"schema": RDF_BODY_SCHEMA}, JSONLD: {"schema": RDF_BODY_SCHEMA}},
    },
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_410_GONE: GONE,
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
        raise_if_series_gone(store, uris, slug)
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


# --- Decisión 49: edición y baja de la serie --------------------------------------------

EDIT_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": schemas.ErrorResponse, "description": "No autenticado"},
    status.HTTP_403_FORBIDDEN: {
        "model": schemas.ErrorResponse,
        "description": "Requiere rol editor o admin",
    },
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_410_GONE: GONE,
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": schemas.ErrorResponse,
        "description": "Triplestore o almacenamiento no disponible",
    },
}


def _crud_error(exc: catalogs.CrudError, uris: UrisDep) -> JSONResponse:
    if exc.status_code == status.HTTP_410_GONE and exc.tombstone is not None:
        return gone_json(exc.tombstone, uris)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@router.patch(
    "/{slug}",
    response_model=schemas.DatasetDetail,
    summary="Edita los metadatos de la serie y la mueve de catálogo (editor o admin)",
    description="Cambia solo los campos presentes de la serie (título, descripción, "
    "publicador) y, con `catalog`, la mueve a otro catálogo (se quita del de origen y se "
    "añade al de destino; ninguna URI cambia). Las versiones publicadas no se tocan "
    "(decisión 28): para cambiarlas se publica una versión nueva con `POST /datasets`. La "
    "serie resultante se valida con SHACL. 422 `catalog` si el catálogo de destino no "
    "existe o está dado de baja.",
    responses={
        **EDIT_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.IngestErrorResponse,
            "description": "Cuerpo no válido, catálogo de destino inexistente o informe SHACL",
        },
    },
)
def update_dataset(
    editor: EditorUser,
    slug: SlugPath,
    data: schemas.DatasetUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.DatasetDetail | JSONResponse:
    try:
        catalogs.update_series(store, db, uris, settings, slug, data, editor)
    except catalogs.CrudError as exc:
        return _crud_error(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    detail = catalog.get_dataset(store, uris, slug)
    if detail.version is not None:
        fair_views.enrich_version(db, uris, slug, detail.version)
    return detail


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Da de baja un dataset (editor o admin)",
    description="Borrado lógico de la serie: sale de su catálogo, de los listados y de "
    "SPARQL; sus ficheros de distribución se eliminan del almacenamiento, y su URI y las "
    "de sus versiones, distribuciones y ficheros responden 410 con una ficha mínima. Su "
    "slug no se reutiliza. Quién la dio de baja queda en la auditoría.",
    responses=EDIT_RESPONSES,
)
def withdraw_dataset(
    editor: EditorUser,
    slug: SlugPath,
    db: DbDep,
    store: StoreDep,
    storage: StorageDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    try:
        catalogs.withdraw_series(store, db, storage, uris, settings, slug, editor)
    except catalogs.CrudError as exc:
        return _crud_error(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    except StorageError as exc:  # pragma: no cover - withdraw_series ya los recoge
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
