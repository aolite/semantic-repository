"""410 Gone de los recursos dados de baja (decisión 49).

``GoneError`` se lanza desde cualquier ruta de la API JSON y el manejador de ``app.main``
responde 410 con la ficha mínima (``schemas.GoneResponse``). Las URIs persistentes
(``/dataset/…``, ``/catalogo/…``) negocian además HTML y RDF (``app.routers.linked_data``).
Una serie dada de baja vale también para lo que cuelga de ella (versiones, distribuciones
y ficheros): se resuelve por el slug, que es el prefijo ``{BASE_URI}dataset/{slug}/``.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app import bajas, catalogs, schemas
from app.triplestore import TripleStore
from app.uris import Uris

GONE = {"model": schemas.GoneResponse, "description": "Dado de baja: ficha mínima (lápida)"}


class GoneError(Exception):
    def __init__(self, tombstone: bajas.Tombstone, uris: Uris) -> None:
        super().__init__(tombstone.uri)
        self.tombstone = tombstone
        self.uris = uris


def raise_if_gone(store: TripleStore, uris: Uris, uri: str) -> None:
    tombstone = bajas.get_tombstone(store, uris, uri)
    if tombstone is not None:
        raise GoneError(tombstone, uris)


def raise_if_series_gone(store: TripleStore, uris: Uris, slug: str) -> None:
    raise_if_gone(store, uris, uris.series(slug))


def gone_json(tombstone: bajas.Tombstone, uris: Uris) -> JSONResponse:
    body = catalogs.gone_response(tombstone, uris)
    return JSONResponse(status_code=status.HTTP_410_GONE, content=body.model_dump())


async def gone_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GoneError)  # noqa: S101 - registrado solo para GoneError
    return gone_json(exc.tombstone, exc.uris)
