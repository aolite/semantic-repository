"""URIs persistentes de datasets con negociación de contenido, y ficheros de distribución.

``{BASE_URI}dataset/…`` se sirve aquí como ``/dataset/…``. En el despliegue, el proxy
inverso envía ``{BASE_URI}dataset/…`` a estas rutas (ver ``backend/README.md``).

Negociación (decisión 31):

- ``text/turtle``, ``application/ld+json`` o ``application/rdf+xml``: el RDF.
- Sin ``Accept``, con ``*/*`` o con ``text/html``: 303 See Other a la ficha del frontend
  (``FRONTEND_BASE_URL``). El RDF solo sale con un ``Accept`` de RDF.

Signposting (https://signposting.org/FAIR/): el 303 y el RDF llevan una cabecera ``Link``
con ``rel="cite-as"`` hacia la URI persistente y ``rel="describedby"`` hacia sus
representaciones RDF (la misma URI con su ``type``), para que un cliente sepa cuál es el
identificador y dónde están los metadatos sin seguir la redirección al frontend.

Rutas:

- ``/dataset/{slug}``: la serie completa.
- ``/dataset/{slug}/{version}``: la versión.
- ``/dataset/{slug}/{version}/{dist}``: la distribución (HTML: ficha, ``#distribuciones``).
- ``/dataset/{slug}/{version}/{dist}/fichero``: el fichero de la distribución, con el
  control de acceso de la decisión 40 (ver ``app.distributions``).
- ``/catalogo``: el catálogo raíz; ``/catalogo/{slug}``: un catálogo (decisión 49).

Bajas (decisión 49): la URI de un catálogo o de una serie dados de baja responde **410
Gone** con una ficha mínima (la lápida): HTML sin ``Accept``, con ``*/*`` o con
``text/html`` (aquí no hay 303, porque el frontend respondería 200), o el RDF de la lápida
con un ``Accept`` de RDF. Las URIs que cuelgan de una serie dada de baja (versión,
distribución y fichero) responden igual, con la lápida de la serie (por el prefijo).
"""

from datetime import UTC, datetime
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from rdflib import Graph, URIRef
from rdflib.namespace import RDF
from sqlalchemy.exc import IntegrityError

from app import audit, bajas, catalog, catalogs, distributions, schemas
from app.deps import DbDep, OptionalUser, SettingsDep, StorageDep, StoreDep, UrisDep
from app.models import AuditAction, DistributionFile, UsedDownloadToken, User
from app.negotiation import HTML, JSONLD, RDFXML, TURTLE, negotiate
from app.routers.datasets import RDF_BODY_SCHEMA
from app.routers.rdf_formats import graph_response
from app.security import InvalidTokenError, decode_download_token, token_revoked
from app.storage import StorageError
from app.uris import DCAT, SLUG_PATTERN, VERSION_PATTERN

router = APIRouter(prefix="/dataset", tags=["linked-data"])
catalog_router = APIRouter(prefix="/catalogo", tags=["linked-data"])

# HTML primero: sin Accept o con */* gana el 303 (decisión 31).
OFFERED = [HTML, TURTLE, JSONLD, RDFXML]

SlugPath = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=200)]
VersionPath = Annotated[str, Path(pattern=VERSION_PATTERN, max_length=50)]
DistPath = Annotated[
    str, Path(pattern=SLUG_PATTERN, max_length=200, description="Slug de la distribución")
]

RESPONSES = {
    status.HTTP_200_OK: {
        "description": "RDF del recurso (solo con un Accept de RDF)",
        "content": {m: {"schema": RDF_BODY_SCHEMA} for m in (TURTLE, JSONLD, RDFXML)},
    },
    status.HTTP_303_SEE_OTHER: {
        "description": "Sin Accept, con */* o con text/html: redirige a la ficha del frontend"
    },
    status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_410_GONE: {
        "description": "Dado de baja (decisión 49): ficha mínima en HTML o RDF de la lápida",
        "content": {
            HTML: {"schema": {"type": "string"}},
            **{m: {"schema": RDF_BODY_SCHEMA} for m in (TURTLE, JSONLD, RDFXML)},
        },
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
}


def _choose(request: Request) -> str:
    media = negotiate(request.headers.get("accept"), OFFERED)
    if media is None:
        raise HTTPException(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            detail="Formatos disponibles: text/html, text/turtle, application/ld+json, "
            "application/rdf+xml",
        )
    return media


def signposting(uri: str) -> str:
    """Valor de la cabecera ``Link`` (RFC 8288) con el signposting de una URI persistente."""
    links = [f'<{uri}>; rel="cite-as"']
    links.extend(
        f'<{uri}>; rel="describedby"; type="{media}"' for media in (TURTLE, JSONLD, RDFXML)
    )
    return ", ".join(links)


def _see_other(url: str, uri: str) -> RedirectResponse:
    return RedirectResponse(
        url,
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Vary": "Accept", "Link": signposting(uri)},
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")


GONE_PAGE = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Recurso dado de baja · {title}</title></head>
<body>
<main>
<h1>Recurso dado de baja</h1>
<dl>
<dt>Título</dt><dd>{title}</dd>
<dt>Tipo</dt><dd>{kind}</dd>
<dt>URI</dt><dd><code>{uri}</code></dd>
<dt>Fecha de baja</dt><dd>{when}</dd>
</dl>
<p>Este recurso ya no está disponible. Su URI se conserva y no se reutiliza.</p>
</main>
</body>
</html>
"""


GONE_KIND_LABELS = {
    "catalog": "Catálogo",
    "dataset": "Dataset",
    "scheme": "Esquema SKOS",
    "ontology": "Ontología",
}


def gone(request: Request, tombstone: bajas.Tombstone, uris: UrisDep) -> Response:
    """410 Gone con la ficha mínima, negociada como el resto de URIs persistentes."""
    media = negotiate(request.headers.get("accept"), OFFERED) or HTML
    if media == HTML:
        kind = GONE_KIND_LABELS[catalogs.gone_kind(uris, tombstone.uri)]
        page = GONE_PAGE.format(
            title=escape(tombstone.title or tombstone.uri),
            kind=kind,
            uri=escape(tombstone.uri),
            when=escape(tombstone.withdrawn_at or ""),
        )
        return HTMLResponse(page, status_code=status.HTTP_410_GONE, headers={"Vary": "Accept"})
    response = _rdf(tombstone.graph(), uris, media, tombstone.uri)
    response.status_code = status.HTTP_410_GONE
    return response


def _gone_or_404(request: Request, store: StoreDep, uris: UrisDep, uri: str) -> Response:
    tombstone = bajas.get_tombstone(store, uris, uri)
    if tombstone is None:
        raise _not_found()
    return gone(request, tombstone, uris)


def _rdf(graph: Graph, uris: UrisDep, media: str, uri: str) -> Response:
    if media == RDFXML:
        response = graph_response(graph, uris, media)
    else:
        from app.routers.datasets import rdf_response

        response = rdf_response(catalog.serialize(graph, uris, _fmt(media)), media)
    response.headers["Link"] = signposting(uri)
    return response


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
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.series(slug))
    uri = uris.series(slug)
    if media == HTML:
        return _see_other(f"{settings.frontend_base_url}/datasets/{quote(slug)}", uri)
    return _rdf(graph, uris, media, uri)


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
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.series(slug))
    uri = uris.version(slug, version)
    if media == HTML:
        return _see_other(
            f"{settings.frontend_base_url}/datasets/{quote(slug)}?version={quote(version)}", uri
        )
    return _rdf(graph, uris, media, uri)


def distribution_rdf(store: StoreDep, uris: UrisDep, slug: str, version: str, dist: str) -> Graph:
    """Triples de la distribución y de los nodos en blanco que cuelgan de ella."""
    source = catalog.series_graph(store, uris, slug)
    series = URIRef(uris.series(slug))
    version_node = URIRef(uris.version(slug, version))
    dist_node = URIRef(f"{uris.version(slug, version)}/{dist}")
    if (
        (series, RDF.type, DCAT.DatasetSeries) not in source
        or (version_node, DCAT.inSeries, series) not in source
        or (version_node, DCAT.distribution, dist_node) not in source
    ):
        raise catalog.NotFoundError(f"{slug}/{version}/{dist}")
    result = Graph()
    catalog.bind_prefixes(result, uris)
    pending: list = [dist_node]
    seen: set = set()
    while pending:
        subject = pending.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for _, predicate, obj in source.triples((subject, None, None)):
            result.add((subject, predicate, obj))
            if not isinstance(obj, URIRef) and (obj, None, None) in source:
                pending.append(obj)
    return result


@router.get(
    "/{slug}/{version}/{dist}",
    summary="URI persistente de una distribución (su dcat:accessURL)",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_distribution(
    request: Request,
    slug: SlugPath,
    version: VersionPath,
    dist: DistPath,
    store: StoreDep,
    uris: UrisDep,
    settings: SettingsDep,
) -> Response:
    media = _choose(request)
    try:
        graph = distribution_rdf(store, uris, slug, version, dist)
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uris.series(slug))
    uri = f"{uris.version(slug, version)}/{dist}"
    if media == HTML:
        return _see_other(
            f"{settings.frontend_base_url}/datasets/{quote(slug)}?version={quote(version)}"
            "#distribuciones",
            uri,
        )
    return _rdf(graph, uris, media, uri)


# --- Fichero de la distribución (decisión 40) -----------------------------------------


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _consume_link(db: DbDep, settings: SettingsDep, token: str, key: str) -> User:
    """Valida el enlace firmado (``?token=``) y lo marca como usado (un solo uso)."""
    try:
        claims = decode_download_token(settings, token)
    except InvalidTokenError as exc:
        raise _unauthorized("Enlace de descarga no válido o caducado") from exc
    if claims.storage_key != key:
        raise _unauthorized("Enlace de descarga no válido o caducado")
    user = db.get(User, claims.user_id)
    if (
        user is None
        or not user.is_active
        or token_revoked(claims.issued_at_us, user.tokens_valid_after)
    ):
        raise _unauthorized("Enlace de descarga no válido o caducado")
    now = datetime.now(UTC)
    db.query(UsedDownloadToken).filter(UsedDownloadToken.expires_at < now).delete()
    db.add(UsedDownloadToken(jti=claims.jti, expires_at=claims.expires_at))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _unauthorized("Enlace de descarga ya usado") from exc
    return user


@router.get(
    "/{slug}/{version}/{dist}/fichero",
    summary="Fichero de una distribución (control de acceso por dct:accessRights)",
    description=(
        "PUBLIC con fichero: cualquiera. RESTRICTED con fichero: `Authorization: Bearer` "
        "válido o `?token=` firmado y vigente (de `POST …/download-link`, un solo uso); sin "
        "ellos 401. NON_PUBLIC o sin fichero: 404. Se sirve en streaming con el "
        "`Content-Type` del RDF y `Content-Disposition: attachment`. Las descargas "
        "RESTRICTED se auditan (`distribution_downloaded`)."
    ),
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Contenido del fichero",
            "content": {"application/octet-stream": {"schema": {"type": "string"}}},
        },
        status.HTTP_401_UNAUTHORIZED: {"model": schemas.ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": schemas.ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
        status.HTTP_410_GONE: RESPONSES[status.HTTP_410_GONE],
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def download_file(
    request: Request,
    slug: SlugPath,
    version: VersionPath,
    dist: DistPath,
    store: StoreDep,
    uris: UrisDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUser,
    token: Annotated[
        str | None,
        Query(max_length=4096, description="Enlace firmado de POST …/download-link"),
    ] = None,
) -> StreamingResponse:
    try:
        info = distributions.lookup(store, uris, slug, version, dist)
    except distributions.DistributionNotFoundError:
        return _gone_or_404(request, store, uris, uris.series(slug))  # type: ignore[return-value]
    record = db.get(DistributionFile, info.storage_key)
    mode = distributions.download_mode(info.access_code, record is not None)
    if mode in ("metadata_only", "unavailable") or record is None:
        raise _not_found()
    actor: User | None = None
    if mode == "authenticated":
        if user is None and token is not None:
            user = _consume_link(db, settings, token, info.storage_key)
        if user is None:
            raise _unauthorized("Descarga restringida: inicia sesión")
        # Hoy todos los roles con cuenta pueden descargar (decisión 40); aquí iría el 403.
        actor = user
    try:
        size = storage.size(info.storage_key)
        chunks = storage.open_stream(info.storage_key)
    except FileNotFoundError as exc:
        raise _not_found() from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if mode == "authenticated":
        audit.record(
            db,
            AuditAction.DISTRIBUTION_DOWNLOADED,
            actor=actor,
            # «enlace»: con un enlace firmado; «sesion»: con la cabecera Authorization.
            details={"storage_key": info.storage_key, "via": "enlace" if token else "sesion"},
        )
        db.commit()
    name = distributions.download_filename(slug, version, dist, record.media_type)
    return StreamingResponse(
        chunks,
        media_type=record.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store" if mode == "authenticated" else "public",
        },
    )


def _fmt(media: str) -> str:
    return "json-ld" if media == JSONLD else "turtle"


# --- Catálogos (decisión 49) ----------------------------------------------------------


@catalog_router.get(
    "",
    summary="URI persistente del catálogo raíz",
    description="RDF del catálogo raíz (agrupa los catálogos con dcat:catalog). Sin Accept, "
    "con */* o con text/html: 303 a la pantalla Catálogo del frontend.",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_root_catalog(
    request: Request, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    media = _choose(request)
    uri = uris.root_catalog
    try:
        graph = catalog.catalog_rdf(store, uris, uri)
    except catalog.NotFoundError as exc:
        raise _not_found() from exc
    if media == HTML:
        return _see_other(f"{settings.frontend_base_url}/", uri)
    return _rdf(graph, uris, media, uri)


@catalog_router.get(
    "/{slug}",
    summary="URI persistente de un catálogo",
    description="RDF del catálogo (con sus dcat:dataset). Sin Accept, con */* o con "
    "text/html: 303 a `{FRONTEND_BASE_URL}/catalogos/{slug}`. Dado de baja: 410.",
    response_class=Response,
    responses=RESPONSES,
)
def resolve_catalog(
    request: Request, slug: SlugPath, store: StoreDep, uris: UrisDep, settings: SettingsDep
) -> Response:
    media = _choose(request)
    uri = uris.catalog(slug)
    try:
        graph = catalog.catalog_rdf(store, uris, uri)
    except catalog.NotFoundError:
        return _gone_or_404(request, store, uris, uri)
    if media == HTML:
        # [PROPUESTA] Ruta de la ficha de catálogo en el frontend (la propone frontend).
        return _see_other(f"{settings.frontend_base_url}/catalogos/{quote(slug)}", uri)
    return _rdf(graph, uris, media, uri)
