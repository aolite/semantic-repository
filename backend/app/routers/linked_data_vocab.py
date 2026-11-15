"""URIs persistentes de ontologías y esquemas SKOS, con negociación de contenido.

- ``{BASE_URI}onto/{slug}``: la versión actual de la ontología. Los términos
  (``{BASE_URI}onto/{slug}#Clase``) se resuelven con ella: el fragmento no llega al
  servidor.
- ``{BASE_URI}onto/{slug}/{version}``: esa versión.
- ``{BASE_URI}vocab/{slug}`` y ``{BASE_URI}vocab/corp/{slug}``: el esquema completo.
- ``{BASE_URI}vocab/{slug}/{concepto}`` y ``…/corp/{slug}/{concepto}``: el concepto.

``text/turtle``, ``application/ld+json`` o ``application/rdf+xml``: el RDF. ``text/html``:
303 See Other al frontend:

- ontologías: ``{FRONTEND_BASE_URL}/ontologias/{slug}`` (``?version=`` en una versión);
- esquemas: ``{FRONTEND_BASE_URL}/vocabularios/{slug}`` o ``/vocabularios/corp/{slug}``
  (``?concepto=`` en un concepto).

Sin ``Accept`` o con ``*/*``: Turtle. Un recurso que no existe da 404 en cualquier formato.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import RedirectResponse
from rdflib import Graph

from app import catalog, schemas, vocabularies
from app.deps import SettingsDep, StoreDep, UrisDep
from app.negotiation import HTML, JSONLD, RDFXML, TURTLE, negotiate
from app.routers.datasets import RDF_BODY_SCHEMA
from app.routers.rdf_formats import graph_response
from app.uris import SLUG_PATTERN, VERSION_PATTERN, Uris

onto_router = APIRouter(prefix="/onto", tags=["linked-data"])
vocab_router = APIRouter(prefix="/vocab", tags=["linked-data"])

OFFERED = [TURTLE, JSONLD, RDFXML, HTML]

SlugPath = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=200)]
VersionPath = Annotated[str, Path(pattern=VERSION_PATTERN, max_length=50)]

RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF del recurso",
        "content": {m: {"schema": RDF_BODY_SCHEMA} for m in (TURTLE, JSONLD, RDFXML)},
    },
    status.HTTP_303_SEE_OTHER: {"description": "Accept: text/html. Redirige al frontend"},
    status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}


def _choose(request: Request) -> str:
    media = negotiate(request.headers.get("accept"), OFFERED)
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Formatos disponibles: text/turtle, application/ld+json, "
            "application/rdf+xml, text/html",
        )
    return media


def _respond(media: str, graph: Graph, uris: Uris, html_url: str) -> Response:
    if media == HTML:
        return RedirectResponse(
            html_url, status_code=status.HTTP_303_SEE_OTHER, headers={"Vary": "Accept"}
        )
    return graph_response(graph, uris, media)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


# --- Ontologías ---------------------------------------------------------------------------


@onto_router.get(
    "/{slug}",
    summary="URI persistente de una ontología (versión actual; también sus términos #…)",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_ontology(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    media = _choose(request)
    try:
        graph = vocabularies.ontology_rdf(store, uris, slug, None)
    except catalog.NotFoundError as exc:
        raise _not_found(exc) from exc
    return _respond(media, graph, uris, f"{settings.frontend_base_url}/ontologias/{quote(slug)}")


@onto_router.get(
    "/{slug}/{version}",
    summary="URI persistente de una versión de ontología (owl:versionIRI)",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_ontology_version(
    request: Request,
    slug: SlugPath,
    version: VersionPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    media = _choose(request)
    try:
        graph = vocabularies.ontology_rdf(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise _not_found(exc) from exc
    url = f"{settings.frontend_base_url}/ontologias/{quote(slug)}?version={quote(version)}"
    return _respond(media, graph, uris, url)


# --- Esquemas SKOS ----------------------------------------------------------------------


def _scheme_url(settings: SettingsDep, slug: str, corp: bool, concept: str | None) -> str:
    path = f"corp/{quote(slug)}" if corp else quote(slug)
    url = f"{settings.frontend_base_url}/vocabularios/{path}"
    return f"{url}?concepto={quote(concept)}" if concept else url


def _scheme(
    request: Request,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
    slug: str,
    corp: bool,
    concept: str | None = None,
) -> Response:
    media = _choose(request)
    try:
        if concept is None:
            graph = vocabularies.scheme_rdf(store, uris, slug, corp)
        else:
            graph = vocabularies.concept_rdf(store, uris, slug, corp, concept)
    except catalog.NotFoundError as exc:
        raise _not_found(exc) from exc
    return _respond(media, graph, uris, _scheme_url(settings, slug, corp, concept))


@vocab_router.get(
    "/corp/{slug}",
    summary="URI persistente de un esquema SKOS corporativo",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_corp_scheme(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    return _scheme(request, store, uris, settings, slug, True)


@vocab_router.get(
    "/corp/{slug}/{concept}",
    summary="URI persistente de un concepto de un esquema corporativo",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_corp_concept(
    request: Request,
    slug: SlugPath,
    concept: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    return _scheme(request, store, uris, settings, slug, True, concept)


@vocab_router.get(
    "/{slug}",
    summary="URI persistente de un esquema SKOS de dominio",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_scheme(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    return _scheme(request, store, uris, settings, slug, False)


@vocab_router.get(
    "/{slug}/{concept}",
    summary="URI persistente de un concepto SKOS",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_concept(
    request: Request,
    slug: SlugPath,
    concept: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    return _scheme(request, store, uris, settings, slug, False, concept)
