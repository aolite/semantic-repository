"""Descarga de RDF: ``Content-Disposition: attachment`` solo con ``?download=true``.

Sin el parámetro, la respuesta se muestra en la página (pestaña «Descripción RDF» de la
ficha de dataset). Con él, el navegador la guarda con un nombre de fichero seguro,
construido solo con slugs y versiones ya validados por su patrón: ``{slug}-{version}.ttl``
(o ``.jsonld``, ``.rdf``). Si un trozo no cumple el patrón seguro, no se usa.
"""

import re
from typing import Annotated

from fastapi import Query, Response

from app.negotiation import JSONLD, RDFXML, TURTLE

EXTENSIONS = {TURTLE: "ttl", JSONLD: "jsonld", RDFXML: "rdf"}
_SAFE = re.compile(r"^[a-z0-9]+([.-][a-z0-9]+)*$")

DownloadQuery = Annotated[
    bool,
    Query(
        description="true (o 1): añade Content-Disposition: attachment con un nombre de "
        "fichero {slug}-{versión}.{ttl|jsonld|rdf}. Por defecto se muestra en línea"
    ),
]


def filename(parts: list[str | None], media: str) -> str:
    safe = [p for p in parts if p and _SAFE.fullmatch(p)]
    return f"{'-'.join(safe) or 'rdf'}.{EXTENSIONS.get(media, 'txt')}"


def apply(response: Response, download: bool, parts: list[str | None], media: str) -> Response:
    if download:
        name = filename(parts, media)
        response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
