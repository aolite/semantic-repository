"""Ontologías propias: ingesta de una versión (editor; admin hereda) y lectura pública."""

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


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


@router.post(
    "",
    response_model=schemas.OntologyIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Publica una versión de ontología validada con SHACL y calcula sus métricas",
    description=(
        "Recibe una versión de ontología (una owl:Ontology `{BASE_URI}onto/{slug}` con "
        "owl:versionIRI `{BASE_URI}onto/{slug}/{version}`) en Turtle o JSON-LD; las IRIs "
        "relativas se resuelven contra BASE_URI. Sustituye por completo el grafo con nombre del "
        "versionIRI. Antes de escribir calcula las métricas OWL (owlready2) y la consistencia "
        "(Pellet) **sin descargar los owl:imports**, y las guarda como metadatos de la versión. "
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
def create_ontology(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    body: Annotated[tuple[bytes, ingest.RdfFormat], Depends(read_rdf_body)],
    db: DbDep,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
    response: Response,
) -> schemas.OntologyIngestResult | JSONResponse:
    data, rdf_format = body
    try:
        graph = ingest.parse_rdf(
            data, rdf_format, uris.base, max_triples=settings.ingest_max_triples
        )
        prepared = vocab_ingest.prepare_ontology(graph, uris, settings)
        # Métricas y consistencia antes de escribir: si owlready2 no puede leerla, 422.
        analysis = vocab_ingest.analyze_ontology(prepared, settings, db)
    except ingest.IngestError as exc:
        return ingest_error_response(exc)
    result = vocab_ingest.publish_ontology_and_audit(
        store, db, prepared, settings, analysis=analysis, actor=editor, via="api"
    )
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
    )


@router.get(
    "/{slug}",
    response_model=schemas.OntologyDetail,
    summary="Ficha de ontología: versión actual (o ?version=), métricas, versionado y usos",
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def get_ontology(
    slug: SlugPath, store: StoreDep, db: DbDep, uris: UrisDep, version: VersionQuery = None
) -> schemas.OntologyDetail:
    try:
        return vocabularies.get_ontology(store, db, uris, slug, version)
    except catalog.NotFoundError as exc:
        raise _not_found(exc) from exc


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
        raise _not_found(exc) from exc
    number = version
    if number is None:
        for value in graph.objects(URIRef(uris.ontology(slug)), OWL.versionIRI):
            parts = uris.ontology_version_parts(str(value))
            number = parts[1] if parts else None
    return downloads.apply(graph_response(graph, uris, media), download, [slug, number], media)
