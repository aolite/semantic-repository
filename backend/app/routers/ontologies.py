"""Ontologías propias: ingesta de una versión, edición y baja (editor; admin hereda) y
lectura pública.

Decisión 50: cada ontología propia está en un catálogo (``?catalog={slug}`` al publicar
una versión), se mueve de catálogo (``PATCH``; sus metadatos están en cada versión, que es
inmutable) y se da de baja con lápida y 410 (también sus versiones, por el prefijo). Las
externas no se gestionan desde la aplicación: 403 ``not_managed``.
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
from app.uris import SLUG_PATTERN, VERSION_PATTERN

router = APIRouter(prefix="/ontologies", tags=["ontologies"])

SlugPath = Annotated[
    str, Path(pattern=SLUG_PATTERN, max_length=200, description="Slug de la ontología")
]
VersionQuery = Annotated[
    str | None,
    Query(pattern=VERSION_PATTERN, max_length=50, description="Versión MAYOR.MENOR.PARCHE"),
]
NOT_FOUND = {"model": schemas.ErrorResponse, "description": "La ontología o la versión no existe"}
FORBIDDEN = {
    "model": schemas.ForbiddenResponse,
    "description": "Requiere rol editor o admin; o kind=not_managed: las ontologías externas "
    "no se gestionan desde la aplicación",
}
UNAVAILABLE = {
    "model": schemas.ErrorResponse,
    "description": "Triplestore no disponible o sin credenciales de escritura",
}


def _not_found(store: StoreDep, uris: UrisDep, slug: str) -> HTTPException:
    """410 si la ontología se dio de baja (también para sus versiones, por el prefijo)."""
    uri = uris.ontology(slug)
    if uris.ontology_slug(uri) is not None:
        raise_if_gone(store, uris, uri)
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


@router.post(
    "",
    response_model=schemas.OntologyIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Publica una versión de ontología validada con SHACL y calcula sus métricas",
    description=(
        "Recibe una versión de ontología (una owl:Ontology `{BASE_URI}onto/{slug}` con "
        "owl:versionIRI `{BASE_URI}onto/{slug}/{version}`) en Turtle o JSON-LD; las IRIs "
        "relativas se resuelven contra BASE_URI. Las versiones son inmutables: si el versionIRI "
        "ya está publicado con otro contenido, 409 `version_immutable`; con el mismo, la "
        "ingesta es idempotente. Decisión 50: la ontología pertenece a un catálogo "
        "(`?catalog={slug}` o el triple «<catálogo> dcat:resource <ontología>» en el RDF), "
        "que se guarda en el grafo del catálogo y no en la versión; 409 `catalog_conflict` si "
        "ya está en otro catálogo (se mueve con PATCH), `withdrawn` si se dio de baja y "
        "`prefix_withdrawn` si su prefijo VANN era de un recurso dado de baja; 422 `catalog` "
        "si el catálogo no existe; 403 `not_managed` si describe una ontología externa. "
        "Antes de escribir calcula las métricas OWL (owlready2) y la "
        "consistencia (Pellet) **sin descargar los owl:imports**, y las guarda como "
        "metadatos de la versión. "
        "201 si la versión es nueva; 200 si ya existía (`changed=false` si era idéntica). "
        "Requiere rol editor (admin hereda los permisos de editor)."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {TURTLE: {"schema": RDF_BODY_SCHEMA}, JSONLD: {"schema": RDF_BODY_SCHEMA}},
        }
    },
    responses={
        status.HTTP_200_OK: {
            "model": schemas.OntologyIngestResult,
            "description": "Versión sustituida",
        },
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: FORBIDDEN,
        status.HTTP_409_CONFLICT: {
            "model": schemas.IngestErrorResponse,
            "description": "La versionIRI ya está publicada con otro contenido "
            "(version_immutable), la ontología está en otro catálogo (catalog_conflict), se "
            "dio de baja (withdrawn) o su prefijo era de un recurso dado de baja "
            "(prefix_withdrawn)",
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
def create_ontology(
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
            description="Catálogo de la ontología (catalogo/{slug}, decisión 50): el backend "
            "añade «<catálogo> dcat:resource <ontología>» antes de validar (si el RDF ya "
            "declara otro, 422). Hace falta si el RDF no lo declara",
        ),
    ] = None,
) -> schemas.OntologyIngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(
            data, rdf_format, uris.base, max_triples=settings.ingest_max_triples
        )
        vocab_ingest.check_not_external(store, uris, graph)
        if catalog_slug is not None:
            graph = vocab_ingest.add_resource_membership(graph, uris, catalog_slug)
        prepared = vocab_ingest.prepare_ontology(graph, uris, settings)
        # Inmutabilidad (409) antes de calcular métricas: no se gasta Pellet en balde.
        store.ensure_writable()
        vocab_ingest.check_ontology_immutable(store, prepared)
        # Métricas y consistencia antes de escribir: si owlready2 no puede leerla, 422.
        analysis = vocab_ingest.analyze_ontology(prepared, settings, db)
        result = vocab_ingest.publish_ontology_and_audit(
            store, db, prepared, settings, analysis=analysis, actor=editor, via="api"
        )
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    metrics, consistency = result.metrics, result.consistency
    return schemas.OntologyIngestResult(
        slug=result.slug,
        uri=result.uri,
        version=result.version,
        version_iri=result.version_iri,
        graph=result.graph_uri,
        triples=result.triples,
        created=result.created,
        changed=result.changed,
        metrics_recomputed=result.metrics_recomputed,
        metrics=schemas.OntologyMetricsRead(
            **{k: metrics[k] for k in schemas.OntologyMetricsRead.model_fields if k in metrics}
        ),
        profile=schemas.OwlProfile(
            name=metrics["profile"], compatible=metrics["compatible_profiles"]
        ),
        consistency=schemas.ConsistencyRead(
            **{k: consistency[k] for k in ("reasoner", "consistent", "unsatisfiable_classes")},
            unsatisfiable=consistency.get("unsatisfiable", []),
            detail=consistency.get("detail"),
        ),
        documentation=schemas.DocumentationCoverageRead(**metrics["documentation"]),
        catalog=result.catalog_uri,
    )


# --- Decisión 50: edición (catálogo) y baja ---------------------------------------------

EDIT_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"model": schemas.ErrorResponse, "description": "No autenticado"},
    status.HTTP_403_FORBIDDEN: FORBIDDEN,
    status.HTTP_404_NOT_FOUND: NOT_FOUND,
    status.HTTP_410_GONE: GONE,
    status.HTTP_503_SERVICE_UNAVAILABLE: UNAVAILABLE,
}


@router.patch(
    "/{slug}",
    response_model=schemas.OntologyDetail,
    summary="Mueve una ontología propia de catálogo (editor o admin)",
    description="Decisión 50: con `catalog`, la quita del catálogo de origen y la añade al de "
    "destino; ninguna URI ni ninguna versión cambia. Sus demás metadatos están en cada "
    "versión, que es inmutable (decisión 28): se cambian publicando una versión nueva con "
    "`POST /ontologies`. 422 `catalog` si el catálogo de destino no existe o está dado de "
    "baja; 403 `not_managed` con las externas.",
    responses={
        **EDIT_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": schemas.IngestErrorResponse,
            "description": "Cuerpo no válido, catálogo de destino inexistente o informe SHACL",
        },
    },
)
def update_ontology(
    editor: EditorUser,
    slug: SlugPath,
    data: schemas.OntologyUpdate,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> schemas.OntologyDetail | JSONResponse:
    try:
        vocab_crud.update_ontology(store, db, uris, settings, slug, data, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return vocabularies.get_ontology(store, db, uris, slug, None)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Da de baja una ontología propia con todas sus versiones (editor o admin)",
    description="Borrado lógico (decisión 50): la ontología sale de su catálogo, de los "
    "listados y de SPARQL (se borran los grafos de todas sus versiones); su URI y las de sus "
    "versiones responden 410 con una ficha mínima. Su slug y su prefijo VANN no se "
    "reutilizan. 409 `in_use` si la importa (`owl:imports`) o usa sus términos una versión "
    "de otra ontología propia viva, con los usos en `used_by`. 403 `not_managed` con las "
    "externas.",
    responses={
        **EDIT_RESPONSES,
        status.HTTP_409_CONFLICT: {
            "model": schemas.ConflictResponse,
            "description": "La usan recursos vivos (kind=in_use, con used_by)",
        },
    },
)
def withdraw_ontology(
    editor: EditorUser,
    slug: SlugPath,
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    try:
        vocab_crud.withdraw_ontology(store, db, uris, settings, slug, editor)
    except catalogs.CrudError as exc:
        return crud_error_response(exc, uris)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{slug}",
    response_model=schemas.OntologyDetail,
    summary="Ficha de ontología: versión actual (o ?version=), métricas, versionado y usos",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_410_GONE: GONE,
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def get_ontology(
    slug: SlugPath, store: StoreDep, db: DbDep, uris: UrisDep, version: VersionQuery = None
) -> schemas.OntologyDetail:
    try:
        return vocabularies.get_ontology(store, db, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise _not_found(store, uris, slug) from exc


@router.get(
    "/{slug}/rdf",
    summary="RDF de una versión de ontología: Turtle, RDF/XML o JSON-LD",
    description="Formato por `?format=` o, si no se indica, por la cabecera `Accept`.",
    response_class=Response,
    responses=RDF_RESPONSES,
)
def get_ontology_rdf(
    request: Request,
    slug: SlugPath,
    store: StoreDep,
    uris: UrisDep,
    version: VersionQuery = None,
    rdf_format: Annotated[RdfFormatParam | None, Query(alias="format")] = None,
    download: downloads.DownloadQuery = False,
) -> Response:
    media = choose_media(request, rdf_format)
    try:
        graph = vocabularies.ontology_rdf(store, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise _not_found(store, uris, slug) from exc
    number = version
    if number is None:
        for value in graph.objects(URIRef(uris.ontology(slug)), OWL.versionIRI):
            parts = uris.ontology_version_parts(str(value))
            number = parts[1] if parts else None
    return downloads.apply(graph_response(graph, uris, media), download, [slug, number], media)
