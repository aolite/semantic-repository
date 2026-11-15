"""URIs persistentes con negociación de contenido.

``{BASE_URI}dataset/{slug}`` y ``{BASE_URI}dataset/{slug}/{version}`` se sirven aquí como
``/dataset/{slug}`` y ``/dataset/{slug}/{version}``. En el despliegue, el proxy inverso
envía ``{BASE_URI}dataset/…`` a estas rutas (ver ``backend/README.md``).

- ``text/turtle`` o ``application/ld+json``: el RDF (de la serie completa o de la versión).
- ``text/html``: 303 See Other a la ficha del frontend (``FRONTEND_BASE_URL``).
- Sin ``Accept`` o con ``*/*``: Turtle.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import RedirectResponse

from app import catalog, schemas
from app.deps import SettingsDep, StoreDep, UrisDep
from app.negotiation import HTML, JSONLD, TURTLE, negotiate
from app.routers.datasets import RDF_BODY_SCHEMA, rdf_response
from app.uris import SLUG_PATTERN, VERSION_PATTERN

router = APIRouter(prefix="/dataset", tags=["linked-data"])

OFFERED = [TURTLE, JSONLD, HTML]

SlugPath = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=200)]
VersionPath = Annotated[str, Path(pattern=VERSION_PATTERN, max_length=50)]

RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF del recurso",
        "content": {TURTLE: {"schema": RDF_BODY_SCHEMA}, JSONLD: {"schema": RDF_BODY_SCHEMA}},
    },
    status.HTTP_303_SEE_OTHER: {
        "description": "Accept: text/html. Redirige a la ficha del frontend"
    },
    status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}


def _choose(request: Request) -> str:
    media = negotiate(request.headers.get("accept"), OFFERED)
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Formatos disponibles: text/turtle, application/ld+json, text/html",
        )
    return media


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER, headers={"Vary": "Accept"})


@router.get(
    "/{slug}",
    summary="URI persistente de una serie de dataset",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_series(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    media = _choose(request)
    try:
        graph = catalog.series_rdf(store, uris, slug)
    except catalog.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    if media == HTML:
        return _see_other(f"{settings.frontend_base_url}/datasets/{quote(slug)}")
    return rdf_response(catalog.serialize(graph, uris, _fmt(media)), media)


@router.get(
    "/{slug}/{version}",
    summary="URI persistente de una versión de dataset",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_version(
    request: Request,
    slug: SlugPath,
    version: VersionPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    media = _choose(request)
    try:
        graph = catalog.version_rdf(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    if media == HTML:
        return _see_other(
            f"{settings.frontend_base_url}/datasets/{quote(slug)}?version={quote(version)}"
        )
    return rdf_response(catalog.serialize(graph, uris, _fmt(media)), media)


def _fmt(media: str) -> str:
    return "json-ld" if media == JSONLD else "turtle"
