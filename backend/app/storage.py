"""Almacenamiento de los ficheros de distribución (decisiones 40 y 41).

``Storage`` es la interfaz que usa el resto del backend; la implementación se elige con
``STORAGE_BACKEND``:

- ``disk`` (MVP): ``DiskStorage``, una carpeta (``STORAGE_DISK_PATH``). Escritura atómica
  (fichero temporal en la misma carpeta + ``os.replace``) y lectura en streaming.
- ``r2`` (despliegue): todavía sin implementar. Elegirlo hace que cada operación falle con
  ``StorageConfigError`` (503 con un mensaje claro). Falta decidir el cliente (``boto3`` u
  otro) y las variables de credenciales; ver ``backend/README.md``.

Claves: ``{slug}/{version}/{dist}``, sin extensión, iguales en disco y en R2. Solo se
construyen con ``storage_key()``, que valida cada segmento con su patrón (slug o versión):
una clave no puede contener ``..``, barras de más ni rutas absolutas. ``DiskStorage``
comprueba además que la ruta resuelta queda dentro de la carpeta raíz.
"""

import hashlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import Settings
from app.uris import is_slug, is_version

CHUNK_SIZE = 64 * 1024


class StorageError(RuntimeError):
    """El almacenamiento no está disponible o la operación ha fallado."""


class StorageConfigError(StorageError):
    """El almacenamiento elegido no está configurado o no está implementado."""


class OutsideRootError(FileNotFoundError):
    """La ruta resuelta (p. ej. por un enlace simbólico) sale de la carpeta raíz.

    Hereda de ``FileNotFoundError``: al leer, el fichero simplemente no existe (404), sin
    revelar nada de la estructura del disco.
    """


def storage_key(slug: str, version: str, dist: str) -> str:
    """``{slug}/{version}/{dist}`` con los segmentos validados (evita path traversal)."""
    if not (is_slug(slug) and is_version(version) and is_slug(dist)):
        raise ValueError("Segmento de la clave de almacenamiento no válido")
    return f"{slug}/{version}/{dist}"


def _check_key(key: str) -> tuple[str, str, str]:
    parts = key.split("/")
    if len(parts) != 3:
        raise ValueError("Clave de almacenamiento no válida")
    slug, version, dist = parts
    storage_key(slug, version, dist)
    return slug, version, dist


@dataclass(frozen=True)
class StoredFile:
    byte_size: int
    sha256: str


class Storage(Protocol):
    def save(self, key: str, source: BinaryIO) -> None:
        """Guarda el contenido de ``source`` (desde su posición actual) de forma atómica."""
        ...

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int: ...

    def open_stream(self, key: str) -> Iterator[bytes]:
        """Contenido en trozos (streaming). ``FileNotFoundError`` si no existe."""
        ...

    def delete(self, key: str) -> None:
        """Borra el fichero (baja de un dataset, decisión 49). No falla si no existe."""
        ...


class DiskStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        _check_key(key)
        root = self.root.resolve()
        path = (root / key).resolve()
        if root not in path.parents:  # defensa en profundidad: nunca fuera de la raíz
            raise OutsideRootError("Clave de almacenamiento fuera de la carpeta raíz")
        return path

    def save(self, key: str, source: BinaryIO) -> None:
        try:
            path = self._path(key)
        except OutsideRootError as exc:
            raise StorageError("No se puede escribir en el almacenamiento de disco") from exc
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".subida-", dir=path.parent)
        except OSError as exc:
            raise StorageError("No se puede escribir en el almacenamiento de disco") from exc
        try:
            with os.fdopen(fd, "wb") as target:
                while chunk := source.read(CHUNK_SIZE):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.replace(tmp_name, path)
        except OSError as exc:
            raise StorageError("No se puede escribir en el almacenamiento de disco") from exc
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except OutsideRootError:
            return False

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def open_stream(self, key: str) -> Iterator[bytes]:
        path = self._path(key)
        handle = path.open("rb")  # FileNotFoundError antes de empezar a responder

        def chunks() -> Iterator[bytes]:
            with handle:
                while chunk := handle.read(CHUNK_SIZE):
                    yield chunk

        return chunks()

    def delete(self, key: str) -> None:
        try:
            path = self._path(key)
        except OutsideRootError:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("No se puede borrar del almacenamiento de disco") from exc
        # Carpetas {slug}/{version} vacías: se quitan, sin salir nunca de la raíz.
        root = self.root.resolve()
        for parent in (path.parent, path.parent.parent):
            if parent == root or root not in parent.parents:
                break
            try:
                parent.rmdir()
            except OSError:
                break


class R2Storage:
    """Cloudflare R2: pendiente de decidir cliente y credenciales (ver el docstring)."""

    def _fail(self) -> StorageConfigError:
        return StorageConfigError(
            "STORAGE_BACKEND=r2 todavía no está implementado; usa STORAGE_BACKEND=disk"
        )

    def save(self, key: str, source: BinaryIO) -> None:
        raise self._fail()

    def exists(self, key: str) -> bool:
        raise self._fail()

    def size(self, key: str) -> int:
        raise self._fail()

    def open_stream(self, key: str) -> Iterator[bytes]:
        raise self._fail()

    def delete(self, key: str) -> None:
        raise self._fail()


def storage_from_settings(settings: Settings) -> Storage:
    if settings.storage_backend == "r2":
        return R2Storage()
    return DiskStorage(settings.storage_disk_path)


def hash_stream(source: BinaryIO) -> StoredFile:
    """Tamaño y SHA-256 de ``source`` (desde el principio). Deja la posición al inicio."""
    source.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    source.seek(0)
    return StoredFile(byte_size=size, sha256=digest.hexdigest())
