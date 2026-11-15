"""Formatos RDF de ontologías y esquemas: ``?format=`` o cabecera ``Accept``."""

from typing import Literal

from fastapi import HTTPException, Request, Response, status
from rdflib import Graph

from app import schemas, vocabularies
from app.negotiation import JSONLD, RDFXML, TURTLE, negotiate
from app.routers.datasets import RDF_BODY_SCHEMA, rdf_response
from app.uris import Uris

RdfFormatParam = Literal["turtle", "rdfxml", "jsonld"]
FORMAT_TO_MEDIA: dict[str, str] = {"turtle": TURTLE, "rdfxml": RDFXML, "jsonld": JSONLD}
MEDIA_TO_SERIALIZER = {TURTLE: "turtle", RDFXML: "xml", JSONLD: "json-ld"}
RDF_MEDIA = [TURTLE, JSONLD, RDFXML]

RDF_RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF en Turtle, JSON-LD o RDF/XML",
        "content": {media: {"schema": RDF_BODY_SCHEMA} for media in RDF_MEDIA},
    },
    status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}


def choose_media(request: Request, rdf_format: RdfFormatParam | None) -> str:
    if rdf_format is not None:
        return FORMAT_TO_MEDIA[rdf_format]
    media = negotiate(request.headers.get("accept"), RDF_MEDIA)
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Formatos disponibles: text/turtle, application/ld+json, application/rdf+xml",
        )
    return media


def graph_response(graph: Graph, uris: Uris, media: str) -> Response:
    """406 (no 500) si el RDF guardado no se puede escribir en RDF/XML (QA-G3-05)."""
    try:
        text = vocabularies.serialize(graph, uris, MEDIA_TO_SERIALIZER[media])
    except vocabularies.NotSerializableError:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Este recurso tiene predicados que RDF/XML no puede representar; pídelo "
            "en text/turtle o application/ld+json",
        ) from None
    return rdf_response(text, media)
