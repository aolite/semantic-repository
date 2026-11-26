"""URIs persistentes de ontologías y esquemas SKOS, con negociación de contenido.

- ``{BASE_URI}onto/{slug}``: la versión actual de la ontología. Los términos
  (``{BASE_URI}onto/{slug}#Clase``) se resuelven con ella: el fragmento no llega al
  servidor.
- ``{BASE_URI}onto/{slug}/{version}``: esa versión.
- ``{BASE_URI}onto/externas/{slug}/{n}`` (decisión 51): la versión ``n`` de una ontología
  externa (fichero oficial y registro). ``{BASE_URI}onto/externas/{slug}``: 303 a la ficha
  (HTML) o a la versión actual (RDF).
- ``{BASE_URI}vocab/{slug}`` y ``{BASE_URI}vocab/corp/{slug}``: el esquema completo.
- ``{BASE_URI}vocab/{slug}/{concepto}`` y ``…/corp/{slug}/{concepto}``: el concepto.

``text/turtle``, ``application/ld+json`` o ``application/rdf+xml``: el RDF. ``text/html``:
303 See Other al frontend:

- ontologías: ``{FRONTEND_BASE_URL}/ontologias/{slug}`` (``?version=`` en una versión);
- esquemas: ``{FRONTEND_BASE_URL}/vocabularios/{slug}`` o ``/vocabularios/corp/{slug}``
  (``?concepto=`` en un concepto).

Sin ``Accept`` o con ``*/*``: 303 al frontend, como con ``text/html`` (decisión 31). El RDF
solo sale con un ``Accept`` de RDF. Un recurso que no existe da 404 en cualquier formato.

Bajas (decisión 50): la URI de un esquema o una ontología dados de baja, y por el prefijo
las de sus conceptos y versiones (los términos ``#…`` caen en la de la ontología), responden
**410 Gone** con la ficha mínima, negociada como en ``app.routers.linked_data``: HTML (sin
303, porque el frontend respondería 200) o el RDF de la lápida.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import RedirectResponse
from rdflib import Graph

from app import bajas, catalog, external_versions, schemas, vocabularies
from app.deps import SettingsDep, StoreDep, UrisDep
from app.negotiation import HTML, JSONLD, RDFXML, TURTLE, negotiate
from app.routers.datasets import RDF_BODY_SCHEMA
from app.routers.linked_data import RESPONSES as DATASET_RESPONSES
from app.routers.linked_data import gone
from app.routers.rdf_formats import graph_response
from app.uris import (
    EXTERNAL_ONTOLOGIES_SLUG,
    EXTERNAL_VERSION_PATTERN,
    SLUG_PATTERN,
    VERSION_PATTERN,
    Uris,
)

onto_router = APIRouter(prefix="/onto", tags=["linked-data"])
vocab_router = APIRouter(prefix="/vocab", tags=["linked-data"])

# HTML primero: sin Accept o con */* gana el 303 al frontend (decisión 31).
OFFERED = [HTML, TURTLE, JSONLD, RDFXML]

SlugPath = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=200)]
VersionPath = Annotated[str, Path(pattern=VERSION_PATTERN, max_length=50)]
ExternalNumberPath = Annotated[str, Path(pattern=EXTERNAL_VERSION_PATTERN, max_length=9)]

RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF del recurso",
        "content": {m: {"schema": RDF_BODY_SCHEMA} for m in (TURTLE, JSONLD, RDFXML)},
    },
    status.HTTP_303_SEE_OTHER: {
        "description": "Sin Accept, con */* o con text/html: redirige al frontend"
    },
    status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_410_GONE: {
        **DATASET_RESPONSES[status.HTTP_410_GONE],
        "description": "Dado de baja (decisión 50): ficha mínima en HTML o RDF de la lápida",
    },
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


def _gone_or_404(request: Request, store: StoreDep, uris: Uris, uri: str) -> Response:
    tombstone = bajas.get_tombstone(store, uris, uri)
    if tombstone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")
    return gone(request, tombstone, uris)


# --- Ontologías ---------------------------------------------------------------------------


# Decisión 51: las versiones de las ontologías externas. Van antes que /{slug}/{version}
# («externas» es un slug reservado de las propias).


def _external_url(settings: SettingsDep, slug: str, number: int | None = None) -> str:
    url = f"{settings.frontend_base_url}/ontologias/externas/{quote(slug)}"
    return f"{url}?version={number}" if number is not None else url


@onto_router.get(
    f"/{EXTERNAL_ONTOLOGIES_SLUG}/{{slug}}",
    summary="Serie de versiones de una ontología externa: 303 a la ficha o a la actual",
    description="Decisión 51. `{BASE_URI}onto/externas/{slug}` no es un recurso RDF: solo "
    "agrupa las versiones. Sin `Accept`, con `*/*` o con `text/html`: 303 a la ficha de la "
    "externa en el frontend (`/ontologias/externas/{slug}`). Con un `Accept` de RDF: 303 a "
    "la versión actual `{BASE_URI}onto/externas/{slug}/{n}`, o 404 si aún no tiene "
    "versiones. 404 si la externa no existe.",
    response_class=Response,
    responses={
        status.HTTP_303_SEE_OTHER: RESPONSES[status.HTTP_303_SEE_OTHER],
        status.HTTP_404_NOT_FOUND: RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_406_NOT_ACCEPTABLE: RESPONSES[status.HTTP_406_NOT_ACCEPTABLE],
        status.HTTP_503_SERVICE_UNAVAILABLE: RESPONSES[status.HTTP_503_SERVICE_UNAVAILABLE],
    },
)
def resolve_external_series(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    media = _choose(request)
    try:
        info = external_versions.find_external(
            external_versions.reference_graph(store, uris), uris, slug
        )
    except external_versions.ExternalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    if media == HTML:
        target = _external_url(settings, slug)
    elif info.versions:
        target = uris.external_version(slug, info.last)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La ontología externa aún no tiene versiones: solo hay su referencia",
        )
    return RedirectResponse(
        target, status_code=status.HTTP_303_SEE_OTHER, headers={"Vary": "Accept"}
    )


@onto_router.get(
    f"/{EXTERNAL_ONTOLOGIES_SLUG}/{{slug}}/{{number}}",
    summary="URI persistente de una versión de ontología externa",
    description="Decisión 51. Con un `Accept` de RDF, el grafo de la versión (fichero "
    "oficial y registro de la versión). Sin `Accept`, con `*/*` o con `text/html`: 303 a la "
    "ficha de la externa (`/ontologias/externas/{slug}?version={n}`). 404 si la externa no "
    "lista esa versión.",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_external_version(
    request: Request,
    slug: SlugPath,
    number: ExternalNumberPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    media = _choose(request)
    try:
        graph = external_versions.version_rdf(store, uris, slug, int(number))
    except external_versions.ExternalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    return _respond(media, graph, uris, _external_url(settings, slug, int(number)))


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
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.ontology(slug))
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
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.ontology(slug))
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
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.scheme(slug, corp=corp))
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
