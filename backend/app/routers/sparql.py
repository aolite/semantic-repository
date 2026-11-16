"""SPARQL público (decisión 42) y consultas guardadas (decisión 43).

- ``GET /sparql?query=…`` y ``POST /sparql`` (``application/sparql-query`` o
  ``application/x-www-form-urlencoded`` con ``query``). Públicos; con un JWT válido se
  aplica el límite de usuario autenticado. Validación, límites y formatos en
  ``app.sparql_public``.
- Límite de frecuencia: ``SPARQL_RATE_ANON_PER_MIN`` por IP y ``SPARQL_RATE_AUTH_PER_MIN``
  por usuario (429 con ``Retry-After``), en la base de datos (``app.ratelimit``). La IP es
  la de la conexión (``request.client``), nunca ``X-Forwarded-For``: detrás de un proxy, la
  única forma de fiarse de esa cabecera es la configuración explícita de uvicorn
  (``FORWARDED_ALLOW_IPS``), ver ``backend/README.md``.
- ``/sparql/queries``: consultas de referencia (de ``semantic/consultas``) y personales.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select

from app import audit, ratelimit, saved_queries, schemas, sparql_public
from app.config import Settings
from app.deps import CurrentUser, DbDep, OptionalUser, SettingsDep
from app.models import AuditAction, SavedQuery, User
from app.negotiation import JSONLD, RDFXML, TURTLE, negotiate

router = APIRouter(prefix="/sparql", tags=["sparql"])

SPARQL_JSON = "application/sparql-results+json"
CSV = "text/csv"
NTRIPLES = "application/n-triples"
SPARQL_QUERY = "application/sparql-query"
FORM = "application/x-www-form-urlencoded"
# Un formulario puede triplicar el tamaño de la consulta al codificarla con %XX.
MAX_FORM_BYTES = 3 * sparql_public.MAX_QUERY_BYTES + 1024

OFFERED: dict[str, list[str]] = {
    "SELECT": [SPARQL_JSON, CSV],
    "ASK": [SPARQL_JSON, CSV],
    "CONSTRUCT": [TURTLE, JSONLD, RDFXML, NTRIPLES],
    "DESCRIBE": [TURTLE, JSONLD, RDFXML, NTRIPLES],
}
GRAPH_SERIALIZERS = {TURTLE: "turtle", JSONLD: "json-ld", RDFXML: "xml", NTRIPLES: "nt"}


def get_query_runner(settings: SettingsDep) -> sparql_public.FusekiQueryRunner:
    """Ejecutor de consultas públicas. Las pruebas lo sustituyen por ``MemoryQueryRunner``."""
    return sparql_public.FusekiQueryRunner(settings.fuseki_url, settings.fuseki_dataset)


RunnerDep = Annotated[sparql_public.FusekiQueryRunner, Depends(get_query_runner)]


def _error(code: int, detail: str, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=code, detail=detail, headers=headers)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _rate_limit(db: DbDep, settings: Settings, request: Request, user: User | None) -> None:
    if user is not None:
        key, limit = f"sparql:user:{user.id}", settings.sparql_rate_auth_per_min
    else:
        key, limit = f"sparql:ip:{_client_ip(request)}", settings.sparql_rate_anon_per_min
    retry_after = ratelimit.hit(db, key, limit)
    if retry_after is not None:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiadas consultas: espera antes de volver a intentarlo",
            {"Retry-After": str(retry_after)},
        )


def _execute(
    text: str,
    request: Request,
    settings: Settings,
    runner: sparql_public.FusekiQueryRunner,
) -> Response:
    try:
        validated = sparql_public.validate(text, settings.base_uri)
    except sparql_public.SparqlRequestError as exc:
        raise _error(exc.status_code, exc.message) from None
    media = negotiate(request.headers.get("accept"), OFFERED[validated.kind])
    if media is None:
        raise _error(
            status.HTTP_406_NOT_ACCEPTABLE,
            f"Formatos para {validated.kind}: " + ", ".join(OFFERED[validated.kind]),
        )
    try:
        result = runner.run(
            validated, max_rows=settings.sparql_max_rows, timeout=settings.sparql_timeout_seconds
        )
    except sparql_public.SparqlRequestError as exc:
        raise _error(exc.status_code, exc.message) from None
    except sparql_public.SparqlTimeoutError:
        raise _error(
            status.HTTP_504_GATEWAY_TIMEOUT,
            f"La consulta superó el tiempo máximo ({settings.sparql_timeout_seconds:g} s)",
        ) from None
    except sparql_public.SparqlBackendError as exc:
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    headers = {"Vary": "Accept"}
    if result.truncated:
        headers["X-Result-Truncated"] = "true"
    if media == SPARQL_JSON:
        return Response(result.to_json(), media_type=SPARQL_JSON, headers=headers)
    if media == CSV:
        return Response(result.to_csv(), media_type="text/csv; charset=utf-8", headers=headers)
    graph = result.graph if result.graph is not None else None
    assert graph is not None  # noqa: S101 - CONSTRUCT/DESCRIBE siempre traen grafo
    try:
        body = graph.serialize(format=GRAPH_SERIALIZERS[media])
    except Exception:  # noqa: BLE001 - p. ej. un predicado que RDF/XML no puede escribir
        raise _error(
            status.HTTP_406_NOT_ACCEPTABLE,
            f"El resultado no se puede escribir en {media}; pídelo en {TURTLE} o {JSONLD}",
        ) from None
    return Response(body, media_type=media, headers=headers)


RESPONSES = {
    status.HTTP_200_OK: {
        "description": "SELECT/ASK: application/sparql-results+json (por defecto) o text/csv. "
        "CONSTRUCT/DESCRIBE: text/turtle (por defecto), application/ld+json, "
        "application/rdf+xml o application/n-triples. Con "
        "`X-Result-Truncated: true` si se ha recortado a SPARQL_MAX_ROWS",
        "content": {
            SPARQL_JSON: {"schema": {"type": "object"}},
            CSV: {"schema": {"type": "string"}},
            TURTLE: {"schema": {"type": "string"}},
            JSONLD: {"schema": {"type": "object"}},
            RDFXML: {"schema": {"type": "string"}},
            NTRIPLES: {"schema": {"type": "string"}},
        },
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": schemas.ErrorResponse,
        "description": "Sintaxis, actualización, SERVICE o FROM fuera del repositorio",
    },
    status.HTTP_401_UNAUTHORIZED: {"description": "Token no válido"},
    status.HTTP_406_NOT_ACCEPTABLE: {"model": schemas.ErrorResponse},
    status.HTTP_413_CONTENT_TOO_LARGE: {"model": schemas.ErrorResponse},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": schemas.ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": schemas.ErrorResponse,
        "description": "Límite de frecuencia; ver Retry-After",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    status.HTTP_504_GATEWAY_TIMEOUT: {"model": schemas.ErrorResponse},
}


@router.get(
    "",
    summary="Endpoint SPARQL público de solo lectura",
    response_class=Response,
    responses=RESPONSES,
)
def sparql_get(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    runner: RunnerDep,
    user: OptionalUser,
    query: Annotated[str, Query(description="Consulta SPARQL (SELECT, ASK, CONSTRUCT o DESCRIBE)")],
) -> Response:
    _rate_limit(db, settings, request, user)
    return _execute(query, request, settings, runner)


async def _read_limited(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise _error(status.HTTP_413_CONTENT_TOO_LARGE, "La consulta supera el máximo de 20 KB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _error(status.HTTP_413_CONTENT_TOO_LARGE, "La consulta supera el máximo de 20 KB")
        chunks.append(chunk)
    return b"".join(chunks)


async def _post_query(request: Request) -> str:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == SPARQL_QUERY:
        raw = await _read_limited(request, sparql_public.MAX_QUERY_BYTES)
    elif content_type == FORM:
        form = parse_qs(
            (await _read_limited(request, MAX_FORM_BYTES)).decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=20,
            encoding="utf-8",
            errors="strict",
        )
        values = form.get("query") or []
        if len(values) != 1:
            raise _error(status.HTTP_400_BAD_REQUEST, "Falta el campo 'query'")
        return values[0]
    else:
        raise _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Content-Type debe ser {SPARQL_QUERY} o {FORM}",
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(status.HTTP_400_BAD_REQUEST, "La consulta debe estar en UTF-8") from None


@router.post(
    "",
    summary="Endpoint SPARQL público de solo lectura (POST)",
    response_class=Response,
    responses=RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                SPARQL_QUERY: {"schema": {"type": "string"}},
                FORM: {
                    "schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    }
                },
            },
        }
    },
)
async def sparql_post(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    runner: RunnerDep,
    user: OptionalUser,
) -> Response:
    _rate_limit(db, settings, request, user)
    try:
        text = await _post_query(request)
    except ValueError:  # UTF-8 no válido o formulario con demasiados campos
        raise _error(
            status.HTTP_400_BAD_REQUEST, "Formulario no válido o consulta que no está en UTF-8"
        ) from None
    return _execute(text, request, settings, runner)


# --- Consultas guardadas ------------------------------------------------------------------


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def _personal(row: SavedQuery) -> schemas.SavedQuery:
    return schemas.SavedQuery(
        id=str(row.id),
        title=row.title,
        hint=row.hint,
        query=row.query,
        kind="personal",
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


@router.get(
    "/queries",
    response_model=list[schemas.SavedQuery],
    summary="Consultas guardadas: las de referencia y, con sesión, las personales",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Token no válido"}},
)
def list_queries(db: DbDep, settings: SettingsDep, user: OptionalUser) -> list[schemas.SavedQuery]:
    result = [
        schemas.SavedQuery(
            id=ref.id,
            title=ref.title,
            hint=ref.hint,
            query=ref.query,
            kind="reference",
            created_at=None,
            updated_at=None,
        )
        for ref in saved_queries.load_references(settings.semantic_dir, settings.base_uri)
    ]
    if user is not None:
        rows = db.scalars(
            select(SavedQuery)
            .where(SavedQuery.owner_id == user.id)
            .order_by(SavedQuery.created_at, SavedQuery.id)
        )
        result.extend(_personal(row) for row in rows)
    return result


def _owned(db: DbDep, user: User, query_id: str) -> SavedQuery:
    """La consulta personal del usuario. 404 si no existe, es de otro o es de referencia."""
    try:
        key = uuid.UUID(query_id)
    except ValueError:
        key = None
    row = db.get(SavedQuery, key) if key is not None else None
    if row is None or row.owner_id != user.id:
        raise _error(status.HTTP_404_NOT_FOUND, "La consulta no existe")
    return row


@router.post(
    "/queries",
    response_model=schemas.SavedQuery,
    status_code=status.HTTP_201_CREATED,
    summary="Guarda una consulta personal (miembro o superior)",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_409_CONFLICT: {
            "model": schemas.ErrorResponse,
            "description": "Se ha alcanzado SAVED_QUERIES_MAX_PER_USER",
        },
    },
)
def create_query(
    payload: schemas.SavedQueryCreate, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> schemas.SavedQuery:
    total = db.scalar(select(func.count()).where(SavedQuery.owner_id == user.id)) or 0
    if total >= settings.saved_queries_max_per_user:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Has alcanzado el máximo de {settings.saved_queries_max_per_user} consultas guardadas",
        )
    now = datetime.now(UTC)
    row = SavedQuery(
        owner_id=user.id,
        title=payload.title,
        hint=payload.hint,
        query=payload.query,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit.record(db, AuditAction.SAVED_QUERY_CREATED, actor=user, details={"query": str(row.id)})
    db.commit()
    return _personal(row)


@router.put(
    "/queries/{query_id}",
    response_model=schemas.SavedQuery,
    summary="Modifica una consulta personal (solo su dueño)",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.ErrorResponse,
            "description": "No existe, es de otro usuario o es de referencia",
        },
    },
)
def update_query(
    query_id: str, payload: schemas.SavedQueryCreate, db: DbDep, user: CurrentUser
) -> schemas.SavedQuery:
    row = _owned(db, user, query_id)
    row.title, row.hint, row.query = payload.title, payload.hint, payload.query
    row.updated_at = datetime.now(UTC)
    db.commit()
    return _personal(row)


@router.delete(
    "/queries/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra una consulta personal (solo su dueño)",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_404_NOT_FOUND: {
            "model": schemas.ErrorResponse,
            "description": "No existe, es de otro usuario o es de referencia",
        },
    },
)
def delete_query(query_id: str, db: DbDep, user: CurrentUser) -> Response:
    row = _owned(db, user, query_id)
    identifier = str(row.id)
    db.delete(row)
    audit.record(db, AuditAction.SAVED_QUERY_DELETED, actor=user, details={"query": identifier})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
