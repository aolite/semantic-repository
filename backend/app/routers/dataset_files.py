"""Fase 4: ficheros de distribución (subida, enlace firmado) y evaluación FAIR por versión.

- ``PUT /datasets/{slug}/versions/{version}/distributions/{dist}/file`` (editor).
- ``POST /datasets/{slug}/versions/{version}/distributions/{dist}/download-link`` (cuenta).
- ``GET /datasets/{slug}/versions/{version}/fair/report`` (público).
- ``POST /datasets/{slug}/versions/{version}/fair`` (editor).

El fichero se sirve en ``/dataset/{slug}/{version}/{dist}/fichero`` (``linked_data``).
"""

from datetime import UTC
from typing import Annotated, Any, BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from fastapi.responses import JSONResponse
from python_multipart.multipart import MultipartParser, parse_options_header

from app import catalog, distributions, fair, fair_views, schemas
from app.config import Settings
from app.deps import CurrentUser, DbDep, SettingsDep, StorageDep, StoreDep, UrisDep
from app.models import DistributionFile
from app.routers.datasets import EditorUser, SlugPath
from app.security import create_download_token
from app.storage import StorageError
from app.uris import SLUG_PATTERN, VERSION_PATTERN

router = APIRouter(prefix="/datasets", tags=["datasets"])

VersionPath = Annotated[
    str, Path(pattern=VERSION_PATTERN, max_length=50, description="Versión MAYOR.MENOR.PARCHE")
]
DistPath = Annotated[
    str, Path(pattern=SLUG_PATTERN, max_length=200, description="Slug de la distribución")
]

# Margen para las cabeceras del multipart al comparar Content-Length con MAX_UPLOAD_MB.
MULTIPART_OVERHEAD = 64 * 1024


def _too_large(settings: Settings) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"El fichero supera el máximo de {settings.max_upload_mb} MB (MAX_UPLOAD_MB)",
    )


class _UploadCollector:
    """Callbacks de ``MultipartParser``: copia el campo ``file`` a un temporal con límite."""

    def __init__(self, sink: BinaryIO, limit: int, too_large: HTTPException) -> None:
        self.sink = sink
        self.limit = limit
        self.too_large = too_large
        self.size = 0
        self.files = 0
        self._field = b""
        self._value = b""
        self._headers: dict[bytes, bytes] = {}
        self._in_file = False

    def callbacks(self) -> Any:
        return {
            "on_part_begin": self.on_part_begin,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_part_data": self.on_part_data,
        }

    def on_part_begin(self) -> None:
        self._headers, self._in_file = {}, False

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]

    def on_header_end(self) -> None:
        self._headers[self._field.lower()] = self._value
        self._field, self._value = b"", b""

    def on_headers_finished(self) -> None:
        _disposition, params = parse_options_header(self._headers.get(b"content-disposition", b""))
        self._in_file = params.get(b"name") == b"file"
        if self._in_file:
            self.files += 1

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._in_file or self.files != 1:
            return
        self.size += end - start
        if self.size > self.limit:
            raise self.too_large
        self.sink.write(data[start:end])


async def read_upload(request: Request, settings: SettingsDep, _editor: EditorUser) -> BinaryIO:
    """Campo ``file`` de un ``multipart/form-data``, leído en streaming y con límite.

    Depende de ``EditorUser``: autenticación y rol antes de leer un solo byte. El
    contenido va a un temporal (en memoria hasta 1 MiB, luego en disco) y se corta en
    cuanto supera ``MAX_UPLOAD_MB`` (413), aunque el cliente no declare
    ``Content-Length``.
    """
    media, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if media != b"multipart/form-data" or not boundary:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type debe ser multipart/form-data con un campo 'file'",
        )
    limit = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD:
        raise _too_large(settings)
    spool = distributions.new_spool()
    collector = _UploadCollector(spool, limit, _too_large(settings))
    parser = MultipartParser(boundary, collector.callbacks())
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
    except HTTPException:
        spool.close()
        raise
    except Exception as exc:
        spool.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="multipart/form-data mal formado"
        ) from exc
    if collector.files != 1:
        spool.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se espera exactamente un campo 'file'",
        )
    spool.seek(0)
    return spool


def _file_read(record: DistributionFile) -> schemas.DistributionFileRead:
    uploaded = record.uploaded_at
    if uploaded.tzinfo is None:
        uploaded = uploaded.replace(tzinfo=UTC)
    return schemas.DistributionFileRead(
        storage_key=record.storage_key,
        byte_size=record.byte_size,
        sha256=record.sha256,
        media_type=record.media_type,
        uploaded_at=uploaded,
    )


def _distribution(
    store: StoreDep, uris: UrisDep, slug: str, version: str, dist: str
) -> distributions.DistributionInfo:
    try:
        return distributions.lookup(store, uris, slug, version, dist)
    except distributions.DistributionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="La distribución no existe"
        ) from exc


@router.put(
    "/{slug}/versions/{version}/distributions/{dist}/file",
    response_model=schemas.DistributionFileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Sube el fichero de una distribución (inmutable)",
    description=(
        "Cuerpo `multipart/form-data` con un campo `file`. El tipo de medio se toma del RDF "
        "(dcat:mediaType; si falta, application/octet-stream), nunca del cliente. 201 si se "
        "guarda; 200 si ya había un fichero con el mismo SHA-256 (idempotente); 409 "
        "`file_exists` si había otro contenido; 409 `non_public` si el dct:accessRights "
        "efectivo es NON_PUBLIC (solo metadatos); 413 si supera MAX_UPLOAD_MB. Requiere rol "
        "editor (admin hereda). Auditoría `distribution_uploaded`."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
    responses={
        status.HTTP_200_OK: {
            "model": schemas.DistributionFileRead,
            "description": "El mismo fichero ya estaba subido",
        },
        status.HTTP_400_BAD_REQUEST: {"model": schemas.ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: {"description": "Requiere rol editor o admin"},
        status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
        status.HTTP_409_CONFLICT: {
            "model": schemas.ErrorResponse,
            "description": "file_exists (otro contenido) o non_public (NON_PUBLIC)",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": schemas.ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": schemas.ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse},
    },
)
def upload_distribution_file(
    editor: EditorUser,  # primero: autenticación y rol antes que el cuerpo
    slug: SlugPath,
    version: VersionPath,
    dist: DistPath,
    body: Annotated[BinaryIO, Depends(read_upload)],
    store: StoreDep,
    uris: UrisDep,
    db: DbDep,
    storage: StorageDep,
    response: Response,
) -> schemas.DistributionFileRead:
    try:
        info = _distribution(store, uris, slug, version, dist)
        result = distributions.upload(db, storage, info, body, actor=editor, via="api")
    except distributions.NonPublicError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="non_public: la distribución es NON_PUBLIC (solo metadatos) y no admite fichero",
        ) from exc
    except distributions.FileExistsConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="file_exists: ya hay un fichero con otro contenido; los ficheros son inmutables",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    finally:
        body.close()
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _file_read(result.record)


@router.post(
    "/{slug}/versions/{version}/distributions/{dist}/download-link",
    response_model=schemas.DownloadLink,
    summary="Enlace de descarga firmado (miembro o superior)",
    description=(
        "Devuelve la ruta del fichero (relativa a la API) con un `?token=` firmado por el "
        "servidor (HMAC), ligado al fichero y al usuario, de un solo uso y válido "
        "DOWNLOAD_LINK_TTL_SECONDS. Así el navegador descarga con un enlace normal sin poner "
        "el JWT en la URL. 404 si la distribución no tiene fichero descargable."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    },
)
def create_download_link(
    user: CurrentUser,
    slug: SlugPath,
    version: VersionPath,
    dist: DistPath,
    store: StoreDep,
    uris: UrisDep,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.DownloadLink:
    info = _distribution(store, uris, slug, version, dist)
    record = db.get(DistributionFile, info.storage_key)
    if distributions.download_mode(info.access_code, record is not None) not in (
        "open",
        "authenticated",
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="La distribución no tiene fichero"
        )
    token, expires_at = create_download_token(
        settings, user_id=user.id, storage_key=info.storage_key
    )
    path = distributions.file_path(slug, version, dist)
    return schemas.DownloadLink(url=f"{path}?token={token}", expires_at=expires_at)


# --- Evaluación FAIR ------------------------------------------------------------------------


def _version_uri(store: StoreDep, uris: UrisDep, slug: str, version: str) -> str:
    try:
        view = catalog.load_series(store, uris, slug)
    except catalog.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe") from exc
    node = view.find_version(version)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe")
    return str(node)


@router.get(
    "/{slug}/versions/{version}/fair/report",
    summary="Informe completo de F-UJI de la última evaluación done (JSON)",
    response_class=JSONResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Respuesta de F-UJI (su esquema FAIRResults) sin URLs internas: "
            "la URL evaluada pasa a ser la URI persistente de la versión y "
            "FAIR_TARGET_BASE_URL pasa a BASE_URI",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    },
)
def get_fair_report(
    slug: SlugPath,
    version: VersionPath,
    store: StoreDep,
    uris: UrisDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    done = fair.latest_done(db, _version_uri(store, uris, slug, version))
    if done is None or done.report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No hay evaluación FAIR terminada"
        )
    report = fair.public_report(
        settings, done.report, evaluated_url=done.evaluated_url, version_uri=done.version_uri
    )
    return JSONResponse(content=report)


@router.post(
    "/{slug}/versions/{version}/fair",
    response_model=schemas.FairSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pide una nueva evaluación FAIR con F-UJI (editor)",
    description=(
        "Encola la evaluación y responde enseguida (202) con el estado `pending` (o el de la "
        "que ya está en curso). Al terminar se audita `fair_evaluated` con su estado."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: {"description": "Requiere rol editor o admin"},
        status.HTTP_404_NOT_FOUND: {"model": schemas.ErrorResponse},
    },
)
def reevaluate_fair(
    editor: EditorUser,
    slug: SlugPath,
    version: VersionPath,
    store: StoreDep,
    uris: UrisDep,
    db: DbDep,
) -> schemas.FairSummary:
    version_uri = _version_uri(store, uris, slug, version)
    fair.request_reevaluation(db, version_uri, editor)
    return fair_views.fair_summary(db, slug, version, version_uri)
