"""Catálogos ``{BASE_URI}catalogo/{slug}`` (decisión 49): lectura pública y CRUD (editor;
admin hereda).

El catálogo raíz ``{BASE_URI}catalogo`` no se crea, edita ni borra por la API: el backend
mantiene su ``dcat:catalog`` al crear o dar de baja un catálogo. Los formularios son JSON;
el backend los convierte a RDF y los valida con las formas SHACL.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse

from app import catalog, catalogs, ingest, schemas
from app.deps import DbDep, SettingsDep, StoreDep, UrisDep, require_role
from app.models import Role, User
from app.routers.datasets import ingest_error_response
from app.routers.gone import GONE, gone_json, raise_if_gone
from app.uris import SLUG_PATTERN

router = APIRouter(prefix="/catalogs", tags=["catalogs"])

EditorUser = Annotated[User, Depends(require_role(Role.EDITOR))]  # admin hereda de editor
CatalogSlug = Annotated[
    str,
    Path(pattern=SLUG_PATTERN, max_length=200, description="Slug del catálogo (catalogo/{slug})"),
]

UNAUTHORIZED = {"model": schemas.ErrorResponse, "description": "No autenticado"}
FORBIDDEN = {"model": schemas.ErrorResponse, "description": "Requiere rol editor o admin"}
NOT_FOUND = {"model": schemas.ErrorResponse, "description": "El catálogo no existe"}
INVALID = {
    "model": schemas.IngestErrorResponse,
    "description": "El RDF resultante no cumple las formas SHACL (o el cuerpo no es válido)",
}
UNAVAILABLE = {
    "model": schemas.ErrorResponse,
    "description": "Triplestore no disponible o sin credenciales de escritura",
}


def crud_error_response(exc: catalogs.CrudError, uris: UrisDep) -> JSONResponse:
    if exc.status_code == status.HTTP_410_GONE and exc.tombstone is not None:
        return gone_json(exc.tombstone, uris)
    content: dict = {"detail": exc.detail}
    if exc.datasets:
        content["datasets"] = exc.datasets
    return JSONResponse(status_code=exc.status_code, content=content)


def _detail(store: StoreDep, uris: UrisDep, slug: str) -> schemas.CatalogDetail:
    try:
        return catalog.get_catalog(store, uris, slug)
    except catalog.NotFoundError as exc:
        raise_if_gone(store, uris, uris.catalog(slug))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc


@router.get(
    "",
    response_model=schemas.CatalogPage,
    summary="Catálogos (lector anónimo)",
    description="Los catálogos `{BASE_URI}catalogo/{slug}`, por título, con su número de "
    "datasets. No incluye el catálogo raíz ni los catálogos dados de baja.",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE},
)
def list_catalogs(store: StoreDep, uris: UrisDep) -> schemas.CatalogPage:
    return catalog.list_catalogs(store, uris)


@router.get(
    "/{slug}",
    response_model=schemas.CatalogDetail,
    summary="Ficha de un catálogo con sus datasets (lector anónimo)",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_410_GONE: GONE,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def get_catalog(slug: CatalogSlug, store: StoreDep, uris: UrisDep) -> schemas.CatalogDetail:
    return _detail(store, uris, slug)


@router.post(
    "",
    response_model=schemas.CatalogDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un catálogo (editor o admin)",
    description="Crea `{BASE_URI}catalogo/{slug}` (vacío) en el grafo con nombre de su URI, "
    "validado con SHACL (`itsh:CatalogShape`), y lo añade al catálogo raíz con "
    "`dcat:catalog`. 409 si el slug ya existe o es de un catálogo dado de baja (los slugs "
    "no se reutilizan).",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_409_CONFLICT: {
            "model": schemas.ErrorResponse,
            "description": "Slug en uso o dado de baja",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def create_catalog(
    editor: EditorUser,
    data: schemas.CatalogCreate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.CatalogDetail | JSONResponse:
    try:
        catalogs.create_catalog(store, db, uris, settings, data, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return _detail(store, uris, data.slug)


@router.patch(
    "/{slug}",
    response_model=schemas.CatalogDetail,
    summary="Edita los metadatos de un catálogo (editor o admin)",
    description="Cambia solo los campos presentes (título, descripción, publicador). Sus "
    "datasets no cambian. El resultado se valida con SHACL.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_410_GONE: GONE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def update_catalog(
    editor: EditorUser,
    slug: CatalogSlug,
    data: schemas.CatalogUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.CatalogDetail | JSONResponse:
    try:
        catalogs.update_catalog(store, db, uris, settings, slug, data, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return _detail(store, uris, slug)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Da de baja un catálogo vacío (editor o admin)",
    description="Borrado lógico: el catálogo sale de los listados, de SPARQL y del raíz, y "
    "su URI responde 410 con una ficha mínima. 409 si todavía tiene datasets (en "
    "`datasets`): antes hay que moverlos o darlos de baja. Su slug no se reutiliza.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "model": schemas.CatalogConflictResponse,
            "description": "El catálogo tiene datasets",
        },
        status.HTTP_410_GONE: GONE,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def withdraw_catalog(
    editor: EditorUser,
    slug: CatalogSlug,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    try:
        catalogs.withdraw_catalog(store, db, uris, settings, slug, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{slug}/datasets",
    response_model=schemas.DatasetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un dataset (serie sin versiones) en el catálogo (editor o admin)",
    description="Crea la serie `{BASE_URI}dataset/{slug}` (dcat:DatasetSeries) en este "
    "catálogo, validada con SHACL junto con su triple de pertenencia. La URI del dataset "
    "no lleva el catálogo. Las versiones se publican después con `POST /datasets` (RDF). "
    "409 si el slug del dataset ya existe o se dio de baja.",
    responses={
        status.HTTP_401_UNAUTHORIZED: UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "model": schemas.ErrorResponse,
            "description": "Slug del dataset en uso o dado de baja",
        },
        status.HTTP_410_GONE: GONE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID,
        status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
    },
)
def create_dataset_in_catalog(
    editor: EditorUser,
    slug: CatalogSlug,
    data: schemas.DatasetCreate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.DatasetDetail | JSONResponse:
    try:
        catalogs.create_series(store, db, uris, settings, slug, data, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return catalog.get_dataset(store, uris, data.slug)
