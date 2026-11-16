"""Ficheros de distribución: subida, estado de descarga y nombre del fichero (decisión 40).

- El RDF publicado **no cambia** al subir un fichero. Tamaño, SHA-256 y tipo de medio se
  guardan en PostgreSQL (``distribution_files``) y salen en la API.
- ``dct:accessRights`` efectivo: el de la distribución o, si no tiene, el de su versión.
  - ``PUBLIC`` con fichero: ``open`` (cualquiera descarga).
  - ``RESTRICTED`` con fichero: ``authenticated`` (miembro o superior; auditado).
  - ``NON_PUBLIC`` (defensa): ``metadata_only``. Nunca se sube ni se sirve fichero.
  - Sin fichero, u otro valor de ``accessRights``: ``unavailable``.
- El tipo de medio se toma del RDF (``dcat:mediaType``), nunca del cliente. Sin
  ``dcat:mediaType`` (p. ej. NPZ), ``application/octet-stream``.
- Ficheros inmutables: si ya hay uno con otro SHA-256, 409 ``file_exists``; con el mismo,
  la subida es idempotente.
"""

import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO, Literal, cast

from rdflib import URIRef
from rdflib.namespace import RDF
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, catalog
from app.models import AuditAction, DistributionFile, User
from app.storage import Storage, hash_stream, storage_key
from app.triplestore import TripleStore
from app.uris import DCAT, DCT, EU_ACCESS_RIGHT, Uris

DownloadMode = Literal["open", "authenticated", "metadata_only", "unavailable"]

DEFAULT_MEDIA_TYPE = "application/octet-stream"
# Segmento reservado: ``{distribución}/fichero`` es la ruta del fichero (sección 2).
FILE_SEGMENT = "fichero"

# Extensión del nombre de descarga según el tipo de medio. Si no está aquí, la extensión
# es el slug de la distribución (convención de semantic/uris.md: ``npz``, ``csv``…).
EXTENSIONS: dict[str, str] = {
    "text/csv": "csv",
    "text/turtle": "ttl",
    "text/plain": "txt",
    "application/json": "json",
    "application/ld+json": "jsonld",
    "application/rdf+xml": "rdf",
    "application/n-triples": "nt",
    "application/vnd.tcpdump.pcap": "pcap",
    "application/vnd.apache.parquet": "parquet",
    "application/zip": "zip",
    "application/gzip": "gz",
    "application/pdf": "pdf",
    "application/xml": "xml",
}
_SAFE_EXT = re.compile(r"^[a-z0-9]{1,16}$")


class DistributionNotFoundError(LookupError):
    pass


class NonPublicError(Exception):
    """``NON_PUBLIC``: solo metadatos (decisión 40)."""


class FileExistsConflictError(Exception):
    """Ya hay un fichero con otro contenido (los ficheros son inmutables)."""


@dataclass(frozen=True)
class DistributionInfo:
    slug: str
    version: str
    dist: str
    uri: str
    storage_key: str
    media_type: str
    access_code: str | None


def access_code(node: object) -> str | None:
    if isinstance(node, URIRef) and str(node).startswith(EU_ACCESS_RIGHT):
        return str(node)[len(EU_ACCESS_RIGHT) :] or None
    return None


def download_mode(code: str | None, has_file: bool) -> DownloadMode:
    if code == "NON_PUBLIC":
        return "metadata_only"
    if not has_file:
        return "unavailable"
    if code == "PUBLIC":
        return "open"
    if code == "RESTRICTED":
        return "authenticated"
    return "unavailable"


def extension(media_type: str, dist: str) -> str:
    ext = EXTENSIONS.get(media_type.lower())
    if ext is None:
        ext = dist if _SAFE_EXT.fullmatch(dist) else "bin"
    return ext


def download_filename(slug: str, version: str, dist: str, media_type: str) -> str:
    """``{slug}-{version}-{dist}.{ext}``: solo segmentos validados por su patrón."""
    return f"{slug}-{version}-{dist}.{extension(media_type, dist)}"


def file_path(slug: str, version: str, dist: str) -> str:
    """Ruta del fichero relativa a la raíz del backend (``/dataset/…/fichero``)."""
    return f"/dataset/{slug}/{version}/{dist}/{FILE_SEGMENT}"


def lookup(store: TripleStore, uris: Uris, slug: str, version: str, dist: str) -> DistributionInfo:
    """La distribución publicada ``{BASE_URI}dataset/{slug}/{version}/{dist}``.

    ``DistributionNotFoundError`` si no existe en el grafo publicado de la serie.
    """
    key = storage_key(slug, version, dist)  # valida los segmentos
    graph = catalog.series_graph(store, uris, slug)
    series = URIRef(uris.series(slug))
    version_node = URIRef(uris.version(slug, version))
    dist_node = URIRef(f"{uris.version(slug, version)}/{dist}")
    if (
        (series, RDF.type, DCAT.DatasetSeries) not in graph
        or (version_node, DCAT.inSeries, series) not in graph
        or (version_node, DCAT.distribution, dist_node) not in graph
    ):
        raise DistributionNotFoundError(key)
    code = access_code(graph.value(dist_node, DCT.accessRights))
    if graph.value(dist_node, DCT.accessRights) is None:
        code = access_code(graph.value(version_node, DCT.accessRights))
    media = catalog.media_type(graph.value(dist_node, DCAT.mediaType))
    if media is None or "/" not in media:
        media = DEFAULT_MEDIA_TYPE
    return DistributionInfo(
        slug=slug,
        version=version,
        dist=dist,
        uri=str(dist_node),
        storage_key=key,
        media_type=media,
        access_code=code,
    )


def new_spool() -> BinaryIO:
    """Fichero temporal para recibir una subida (en memoria hasta 1 MiB, luego en disco)."""
    return cast(BinaryIO, tempfile.SpooledTemporaryFile(max_size=1024 * 1024))


@dataclass(frozen=True)
class UploadResult:
    record: DistributionFile
    created: bool


def upload(
    session: Session,
    storage: Storage,
    info: DistributionInfo,
    source: BinaryIO,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    via: str = "api",
) -> UploadResult:
    """Guarda el fichero (atómico) y su registro. Mismas reglas en la API y en la CLI."""
    if info.access_code == "NON_PUBLIC":
        raise NonPublicError(info.storage_key)
    stored = hash_stream(source)
    existing = session.get(DistributionFile, info.storage_key)
    if existing is not None:
        return _repeated(storage, info, existing, stored.sha256, source)
    record = DistributionFile(
        storage_key=info.storage_key,
        distribution_uri=info.uri,
        media_type=info.media_type,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        uploaded_by=actor.id if actor else None,
        uploaded_at=datetime.now(UTC),
    )
    session.add(record)
    # El registro se inserta antes de escribir el fichero: con subidas simultáneas de la
    # misma distribución, la clave primaria deja pasar a una sola (las demás esperan a que
    # termine y reciben IntegrityError) y nadie sobrescribe el fichero de otra.
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        winner = session.get(DistributionFile, info.storage_key)
        if winner is None:  # pragma: no cover - la otra subida se deshizo
            raise
        return _repeated(storage, info, winner, stored.sha256, source)
    try:
        storage.save(info.storage_key, source)
    except BaseException:
        session.rollback()
        raise
    audit.record(
        session,
        AuditAction.DISTRIBUTION_UPLOADED,
        actor=actor,
        actor_username=actor_username,
        details={
            "storage_key": info.storage_key,
            "distribution": info.uri,
            "media_type": info.media_type,
            "byte_size": stored.byte_size,
            "sha256": stored.sha256,
            "via": via,
        },
    )
    session.commit()
    return UploadResult(record, created=True)


def _repeated(
    storage: Storage,
    info: DistributionInfo,
    existing: DistributionFile,
    sha256: str,
    source: BinaryIO,
) -> UploadResult:
    """Subida de una distribución que ya tiene fichero: idempotente o 409."""
    if existing.sha256 != sha256:
        raise FileExistsConflictError(info.storage_key)
    if not storage.exists(info.storage_key):
        # El registro existe pero el fichero se perdió: se vuelve a escribir el mismo.
        storage.save(info.storage_key, source)
    return UploadResult(existing, created=False)


def files_by_uri(session: Session, uris_: list[str]) -> dict[str, DistributionFile]:
    if not uris_:
        return {}
    rows = session.scalars(
        select(DistributionFile).where(DistributionFile.distribution_uri.in_(uris_))
    )
    return {row.distribution_uri: row for row in rows}
